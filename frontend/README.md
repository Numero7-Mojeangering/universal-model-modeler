the purpose of the frontend is to communicate with the user

render fun things
play sound
read keyboard / mouse inputs

another app will be made 


# Install help
On ubuntu, to help you install python3.11 you can install
```bash
sudo add-apt-repository ppa:deadsnakes/ppa -y
```
Then
```bash
sudo apt install python3.11 python3.11-venv -y
```
You can then create a virtual environnement inside the frondent/python directory.
```bash
python3.11 -m venv venv
source venv/bin/activate
```
Install dependencies in the venv:
```bash
pip install -r requirements.txt
```
With the venv activated and dependencies installed, you can now run the frontend :
```bash
python main.py
```
Notice there it's python and not python3.
Typing :
```bash
python --version
```
Should return python version 3.11.X

Once you are done you can deactivate the venv by entering :
```bash
deactivate
```
