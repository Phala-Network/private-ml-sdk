import json

import jwt
import requests

RED_PILL_ATTESTATION_ENDPOINT = "https://api.red-pill.ai/v1/attestation/report"
DEEPSEEK_MODEL = "phala/deepseek-r1-70b"
LLAMA_MODEL = "phala/llama-3.3-70b-instruct"
API_KEY = "sk-"
NVIDIA_ATTESTATION_ENDPOINT = "https://nras.attestation.nvidia.com/v3/attest/gpu"


def verify_nvidia_payload(nvidia_payload: dict):
    response = requests.request(
        "POST",
        NVIDIA_ATTESTATION_ENDPOINT,
        headers={"Content-Type": "application/json"},
        data=nvidia_payload,
    )
    data = response.json()

    # Parse Jwt token from response
    print("NVIDIA NRAS Response", data)
    print(
        "Parsed JWT",
        json.dumps(
            jwt.decode(data[0][1], options={"verify_signature": False}),
            indent=4,
        ),
    )
    print(
        "Parsed JWT GPU-0",
        json.dumps(
            jwt.decode(data[1]["GPU-0"], options={"verify_signature": False}),
            indent=4,
        ),
    )


def verify(model_name: str, signing_algo: str):
    print("### Verifying", model_name, signing_algo)
    response = requests.request(
        "GET",
        f"{RED_PILL_ATTESTATION_ENDPOINT}?model={model_name}&signing_algo={signing_algo}",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    data = response.json()
    nvidia_payload = data["nvidia_payload"]
    verify_nvidia_payload(nvidia_payload)


if __name__ == "__main__":
    verify(DEEPSEEK_MODEL, "ecdsa")
    verify(DEEPSEEK_MODEL, "ed25519")
    verify(LLAMA_MODEL, "ecdsa")
    verify(LLAMA_MODEL, "ed25519")
