# Third-party notices

This project uses third-party software and models. Their licenses and
attribution requirements are summarized below.

## Vosk

This project uses [Vosk](https://github.com/alphacep/vosk-api), an offline
speech recognition toolkit developed by Alpha Cephei.

- Project: https://github.com/alphacep/vosk-api
- License: Apache License, Version 2.0
- License text: [`licenses/VOSK-LICENSE.txt`](licenses/VOSK-LICENSE.txt)

Vosk is used for local, offline speech recognition.

## Vosk models

Streamer Censoring Multitool (SCM) supports the following downloadable Vosk
models:

- `vosk-model-el-gr-0.7` — Greek model  
  Source: https://alphacephei.com/vosk/models  
  License: Apache License, Version 2.0

- `vosk-model-small-en-us-0.15` — English model  
  Source: https://alphacephei.com/vosk/models  
  License: Apache License, Version 2.0

The models are downloaded by the application’s model setup tool from the
official Alpha Cephei website. Users are responsible for complying with the
license terms applicable to the models they download and use.

## Vision & Audio / OBS Components

Streamer Censoring Multitool (SCM) integrates third-party libraries and model
runtimes depending on enabled audio and vision features:

- `python-sounddevice` ([spatialaudio/python-sounddevice](https://github.com/spatialaudio/python-sounddevice), MIT License — see [`licenses/PYTHON-SOUNDDEVICE-LICENSE.txt`](licenses/PYTHON-SOUNDDEVICE-LICENSE.txt))
- `pyaudiowpatch` for Windows WASAPI loopback audio capture
- `obsws-python` for OBS Studio WebSocket integration
- `ultralytics` (`YOLOE`) and `nudenet` for local vision/exposure guards
- Python and Tkinter under the Python Software Foundation license terms included with the Python distribution

Each third-party package and model weight remains subject to its own license
and terms.

## Python dependencies

Python package dependencies and their versions are declared in the project
dependency file. Each dependency remains subject to its own license.

## Privacy

Streamer Censoring Multitool (SCM) processes audio and webcam frames locally
for speech recognition, audio monitoring, and content guarding. This
repository does not collect, upload, or distribute user audio, microphone
recordings, stream recordings, recognition transcripts, or webcam frames.