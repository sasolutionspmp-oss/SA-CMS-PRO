python -m pip install -r ..\requirements.txt
pyinstaller ..\main.py --noconfirm --onedir --hidden-import multipart.multipart --hidden-import starlette.datastructures --distpath dist
Copy-Item ..\assets -Destination dist -Recurse -Force
if (-not (Test-Path "$env:ProgramData\SA-CMS-Pro\logs")) { New-Item -ItemType Directory -Path "$env:ProgramData\SA-CMS-Pro\logs" | Out-Null }
