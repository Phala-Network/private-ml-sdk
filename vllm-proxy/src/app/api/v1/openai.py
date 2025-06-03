import json
import time
from hashlib import sha256

import httpx
from app.api.helper.auth import verify_authorization_header
from app.api.response.response import error, invalid_signing_algo
from app.cache.cache import cache
from app.db.mongo import mongo_metrics
from app.logger import log
from app.quote.quote import ECDSA, ED25519, ecdsa_quote, ed25519_quote
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import (JSONResponse, PlainTextResponse,
                               StreamingResponse)

router = APIRouter(tags=["openai"])

VLLM_BASE_URL = "http://vllm:8000"
VLLM_URL = f"{VLLM_BASE_URL}/v1/chat/completions"
VLLM_COMPLETIONS_URL = f"{VLLM_BASE_URL}/v1/completions"
VLLM_METRICS_URL = f"{VLLM_BASE_URL}/metrics"
VLLM_MODELS_URL = f"{VLLM_BASE_URL}/v1/models"
TIMEOUT = 60 * 10

COMMON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def sign_request(request: dict, response: str):
    content = json.dumps(request.get("messages", [])) + "\n" + response
    return quote.sign(content)


def hash(payload: str):
    return sha256(payload.encode()).hexdigest()


def sign_chat(text: str):
    return dict(
        text=text,
        signature_ecdsa=ecdsa_quote.sign(text),
        signing_address_ecdsa=ecdsa_quote.signing_address,
        signature_ed25519=ed25519_quote.sign(text),
        signing_address_ed25519=ed25519_quote.signing_address,
    )


async def stream_vllm_response(
    url: str, request_body: bytes, modified_request_body: bytes, metrics: dict = None
):
    """
    Handle streaming vllm request
    Args:
        request_body: The original request body
        modified_request_body: The modified enhanced request body
    Returns:
        A streaming response
    """
    if metrics is None:
        metrics = {}
    request_sha256 = sha256(request_body).hexdigest()

    chat_id = None
    h = sha256()
    t0 = time.time()
    first_token_time = None
    step_times = {}
    step_times["start"] = t0

    async def generate_stream(response):
        nonlocal chat_id, h, first_token_time
        async for chunk in response.aiter_text():
            now = time.time()
            h.update(chunk.encode())
            # Extract the cache key (data.id) from the first chunk
            if not chat_id:
                try:
                    data = chunk.strip("data: ").strip()
                    chunk_data = json.loads(data)
                    chat_id = chunk_data.get("id")
                    first_token_time = now
                    step_times["first_token"] = first_token_time
                except Exception as e:
                    error_message = f"Failed to parse the first chunk: {e}"
                    log.error(error_message)
                    raise Exception(error_message)
            yield chunk

        t_cache_start = time.time()
        response_sha256 = h.hexdigest()
        step_times["cache_start"] = t_cache_start
        # Cache the full request and response using the extracted cache key
        if chat_id:
            cache.set_chat(
                chat_id, json.dumps(sign_chat(f"{request_sha256}:{response_sha256}"))
            )
        else:
            error_message = "Chat id could not be extracted from the response"
            log.error(error_message)
            raise Exception(error_message)
        t_end = time.time()
        step_times["end"] = t_end
        # Save metrics to MongoDB
        metrics_doc = {
            "type": "stream",
            "chat_id": chat_id,
            "request_sha256": request_sha256,
            "step_times": step_times,
            "total_time": t_end - t0,
            "first_token_time": (first_token_time - t0) if first_token_time else None,
            "cache_set_cost": t_end - t_cache_start,
            "request_cost": t_end - t0,
            "timestamp": t0,
            "request_body": request_body,
        }
        try:
            mongo_metrics.insert_one(metrics_doc)
        except Exception as e:
            log.error(f"Failed to save metrics to MongoDB: {e}")

    client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT), headers=COMMON_HEADERS)
    # Forward the request to the vllm backend
    t1 = time.time()
    req = client.build_request("POST", url, content=modified_request_body)
    t2 = time.time()
    response = await client.send(req, stream=True)
    t3 = time.time()
    # If not 200, return the error response directly without streaming
    if response.status_code != 200:
        error_content = await response.aread()
        await response.aclose()
        await client.aclose()
        return JSONResponse(
            status_code=response.status_code, content=json.loads(error_content)
        )
    step_times["build_request"] = t2
    step_times["send_request"] = t3

    return StreamingResponse(
        generate_stream(response),
        background=BackgroundTasks([response.aclose, client.aclose]),
    )


# Function to handle non-streaming responses
async def non_stream_vllm_response(
    url: str, request_body: bytes, modified_request_body: bytes, metrics: dict = None
):
    """
    Handle non-streaming responses
    Args:
        request_body: The original request body
        modified_request_body: The modified enhanced request body
    Returns:
        The response data
    """
    if metrics is None:
        metrics = {}
    request_sha256 = sha256(request_body).hexdigest()
    t0 = time.time()
    step_times = {"start": t0}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT), headers=COMMON_HEADERS
    ) as client:
        t1 = time.time()
        response = await client.post(url, content=modified_request_body)
        t2 = time.time()
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        response_data = response.json()
        # Cache the request-response pair using the chat ID
        t_cache_start = time.time()
        chat_id = response_data.get("id")
        step_times["cache_start"] = t_cache_start
        if chat_id:
            response_text = json.dumps(response_data)
            response_sha256 = sha256(response_text.encode()).hexdigest()
            cache.set_chat(
                chat_id, json.dumps(sign_chat(f"{request_sha256}:{response_sha256}"))
            )
        else:
            raise Exception("Chat id could not be extracted from the response")
        t3 = time.time()
        step_times["post_request"] = t1
        step_times["response_received"] = t2
        step_times["end"] = t3
        # Save metrics to MongoDB
        metrics_doc = {
            "type": "non_stream",
            "chat_id": chat_id,
            "request_sha256": request_sha256,
            "step_times": step_times,
            "total_time": t3 - t0,
            "cache_set_cost": t3 - t_cache_start,
            "request_cost": t3 - t0,
            "timestamp": t0,
            "request_body": request_body,
        }
        try:
            mongo_metrics.insert_one(metrics_doc)
        except Exception as e:
            log.error(f"Failed to save metrics to MongoDB: {e}")
        return response_data


def strip_empty_tool_calls(payload: dict) -> dict:
    """
    Strip empty tool calls from the payload
    To fix the bug of:
    https://github.com/vllm-project/vllm/pull/14054
    """
    if "messages" not in payload:
        return payload

    filtered_messages = []
    for message in payload["messages"]:
        # If the message has tool_calls, filter out empty ones
        if "tool_calls" in message and len(message["tool_calls"]) == 0:
            del message["tool_calls"]
        filtered_messages.append(message)

    payload["messages"] = filtered_messages
    return payload


# Get attestation report of intel quote and nvidia payload
@router.get("/attestation/report", dependencies=[Depends(verify_authorization_header)])
async def attestation_report(request: Request, signing_algo: str = None):
    signing_algo = ECDSA if signing_algo is None else signing_algo
    if signing_algo not in [ECDSA, ED25519]:
        return invalid_signing_algo()

    data = dict(
        ecdsa=dict(
            signing_address=ecdsa_quote.signing_address,
            intel_quote=ecdsa_quote.intel_quote,
            nvidia_payload=ecdsa_quote.nvidia_payload,
        ),
        ed25519=dict(
            signing_address=ed25519_quote.signing_address,
            intel_quote=ed25519_quote.intel_quote,
            nvidia_payload=ed25519_quote.nvidia_payload,
        ),
    )
    cache.set_attestation(ecdsa_quote.signing_address, data)

    resp = data[signing_algo]
    try:
        attestations = cache.get_attestations() or []
        resp["all_attestations"] = [a[signing_algo] for a in attestations]
        return resp
    except Exception as e:
        log.error(f"Error parsing the attestations in cache: {e}")
        return resp


# VLLM Chat completions
@router.post("/chat/completions", dependencies=[Depends(verify_authorization_header)])
async def chat_completions(request: Request):
    t0 = time.time()
    # Get the JSON body from the incoming request
    request_body = await request.body()
    t1 = time.time()
    request_json = json.loads(request_body)
    t2 = time.time()
    request_json = strip_empty_tool_calls(request_json)
    t3 = time.time()

    # Check if the request is for streaming or non-streaming
    is_stream = request_json.get(
        "stream", False
    )  # Default to streaming if not specified

    modified_request_body = json.dumps(request_json).encode("utf-8")
    t4 = time.time()
    step_times = {
        "start": t0,
        "read_body": t1,
        "parse_json": t2,
        "strip_empty_tool_calls": t3,
        "encode_body": t4,
    }
    metrics = {"step_times": step_times}
    if is_stream:
        # Create a streaming response
        return await stream_vllm_response(
            VLLM_URL, request_body, modified_request_body, metrics
        )
    else:
        # Handle non-streaming response
        response_data = await non_stream_vllm_response(
            VLLM_URL, request_body, modified_request_body, metrics
        )
        return JSONResponse(content=response_data)


# VLLM completions
@router.post("/completions", dependencies=[Depends(verify_authorization_header)])
async def completions(request: Request):
    t0 = time.time()
    # Get the JSON body from the incoming request
    request_body = await request.body()
    t1 = time.time()
    request_json = json.loads(request_body)
    t2 = time.time()
    request_json = strip_empty_tool_calls(request_json)
    t3 = time.time()

    # Check if the request is for streaming or non-streaming
    is_stream = request_json.get(
        "stream", False
    )  # Default to streaming if not specified

    modified_request_body = json.dumps(request_json).encode("utf-8")
    t4 = time.time()
    step_times = {
        "start": t0,
        "read_body": t1,
        "parse_json": t2,
        "strip_empty_tool_calls": t3,
        "encode_body": t4,
    }
    metrics = {"step_times": step_times}
    if is_stream:
        # Create a streaming response
        return await stream_vllm_response(
            VLLM_COMPLETIONS_URL, request_body, modified_request_body, metrics
        )
    else:
        # Handle non-streaming response
        response_data = await non_stream_vllm_response(
            VLLM_COMPLETIONS_URL, request_body, modified_request_body, metrics
        )
        return JSONResponse(content=response_data)


# Get signature for chat_id of chat history
@router.get("/signature/{chat_id}", dependencies=[Depends(verify_authorization_header)])
async def signature(request: Request, chat_id: str, signing_algo: str = None):
    cache_value = cache.get_chat(chat_id)
    if cache_value is None:
        return error("Chat id not found or expired", "chat_id_not_found")

    signature = None
    signing_algo = ECDSA if signing_algo is None else signing_algo

    # Retrieve the cached request and response
    try:
        value = json.loads(cache_value)
    except Exception as e:
        return error(f"Failed to parse the cache value: {e}", "invalid_cache_value")

    signing_address = None
    if signing_algo == ECDSA:
        signature = value.get("signature_ecdsa")
        signing_address = value.get("signing_address_ecdsa")
    elif signing_algo == ED25519:
        signature = value.get("signature_ed25519")
        signing_address = value.get("signing_address_ed25519")
    else:
        return invalid_signing_algo()

    return dict(
        text=value.get("text"),
        signature=signature,
        signing_address=signing_address,
        signing_algo=signing_algo,
    )


# Metrics of vLLM instance
@router.get("/metrics")
async def metrics(request: Request):
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT)) as client:
        response = await client.get(VLLM_METRICS_URL)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return PlainTextResponse(response.text)


@router.get("/models")
async def models(request: Request):
    async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT)) as client:
        response = await client.get(VLLM_MODELS_URL)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return JSONResponse(content=response.json())
