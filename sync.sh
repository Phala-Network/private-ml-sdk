rsync -azP \
    --exclude .venv \
    --exclude .git \
    --delete \
    ./ phala-s-gpu08-208:'~/private-ml-sdk/'
