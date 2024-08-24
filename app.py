import asyncio
from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import socketio
from openai import OpenAI
import os
from copy import deepcopy
from threading import Lock

# Initialize FastAPI app
app = FastAPI()

# Initialize Socket.IO server with ASGI mode
sio = socketio.AsyncServer(async_mode='asgi')

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Wrap the FastAPI app with the ASGI app provided by socketio
socketio_app = socketio.ASGIApp(sio, app)

# Initialize Jinja2 templates directory
templates = Jinja2Templates(directory="templates")

# Access OpenAI API key from environment variable
api_key = os.getenv("OPENAI_API_KEY_CHATROOM")
if not api_key:
    raise ValueError("OPENAI_API_KEY_CHATROOM environment variable is not set.")
client = OpenAI(api_key=api_key)

# Track active chatrooms and user preferences
active_chatrooms = set()
user_language_preferences = {}
lock = Lock()  # Initialize a lock

async def translate_message(message: str, target_language: str) -> str:
    if target_language == "korean":
        prompt = f"the message is defined by the words in between the two instances of the following code 98457943759gfrhsgSFIUSFEFFE&&$(#((#(##(#, do not return the code. if the message has any parts that are already in Korean, leave them unaltered, including slang, abbreviations - should be exact copy. DO NOT CHANGE ANYTHING ABOUT IT. otherwise, for the parts that are not, with the expertise of a world-class translator of Korean to English, only return the translated message contents in Korean, tending towards an informal tone. Some of the message may be in american slang or texting slang, if so, translate into similiar korean slang. If you are unable to translate the message, simply return the exact message unaltered. in all cases keep the same capitalization, punctuation, and spelling mistakes that the orignal message has: 98457943759gfrhsgSFIUSFEFFE&&$(#((#(##(# {message} 98457943759gfrhsgSFIUSFEFFE&&$(#((#(##(#. Make sure not to return the code and only the message contents!"
    else:
        prompt = f"the message is defined by the words in between the two instances of the following code 98457943759gfrhsgSFIUSFEFFE&&$(#((#(##(#, do not return the code. if the message has any parts that are already in English, leave them unaltered, including slang, abbreviations - should be exact copy. DO NOT CHANGE ANYTHING ABOUT IT. otherwise, for the parts that are not, with the expertise of a world-class translator of Korean to English, only return the translated message contents in English, tending towards an informal tone. Some of the message may be in korean slang or texting slang, if so, translate into similiar american slang. If you are unable to translate the message, simply return the exact message unaltered. in all cases keep the same capitalization,punctuation, and spelling mistakes that the orignal message has: 98457943759gfrhsgSFIUSFEFFE&&$(#((#(##(# {message} 98457943759gfrhsgSFIUSFEFFE&&$(#((#(##(#. Make sure not to return the code and only the message contents!"

    try:
        response = await asyncio.to_thread(client.chat.completions.create, model="gpt-4o", messages=[
            {"role": "system", "content": "You are the world's greatest translator of English to Korean and Korean to English. You expertly convey the subtle emotion and tone of messages..."},
            {"role": "user", "content": prompt}
        ])
        
        translated_message = response.choices[0].message.content.strip()
        print(f"[DEBUG] Translated message: {translated_message}")  # Debugging line

        if not translated_message:
            print(f"[ERROR] Translation resulted in an empty message for '{message}' to '{target_language}'")
            translated_message = message  # Fallback to the original message

        return translated_message

    except Exception as e:
        print(f"[ERROR] Failed to translate message '{message}' to '{target_language}': {e}")
        return message  # Fallback to original message if translation fails

@sio.event
async def connect(sid, environ):
    print("Client connected:", sid)

@sio.event
async def join(sid, data):
    username = data['username']
    room = data['room']

    # Save user session and add user to the room
    await sio.save_session(sid, {'username': username, 'room': room})
    await sio.enter_room(sid, room)
    print(f"[DEBUG] {username} joined room {room}")
    print(f"[DEBUG] Session saved for {sid}: {{'username': '{username}', 'room': '{room}'}}")

    # Fetch and emit updated user list
    await update_user_list(room)

@sio.event
async def disconnect(sid, *args):
    print(f"Client disconnected: {sid}")
    await leave(sid)

@sio.event
async def leave(sid, *args):
    print(f"Handling leave for SID: {sid}")

    # Retrieve session data to determine the username and room
    session = await sio.get_session(sid)
    if session:
        username = session.get('username')
        room = session.get('room')

        if room:
            # Leave the room
            await sio.leave_room(sid, room)
            print(f"[DEBUG] {username} left room {room}")

            # Fetch and emit updated user list
            await update_user_list(room)

    # Clean up the session
    await sio.save_session(sid, {})

async def update_user_list(room):
    user_list = []
    print(f"[DEBUG] Retrieving user list for room '{room}'")  # Debugging line to indicate we're fetching the user list
    print(f"[DEBUG] Current state of rooms: {sio.manager.rooms}")  # Debugging line to see rooms dictionary state

    with lock:
        # Create a snapshot of the current room members
        room_members_snapshot = deepcopy(sio.manager.rooms['/'].get(room, {}))
    
    print(f"[DEBUG] Users in room '{room}' (snapshot): {room_members_snapshot}")  # Debugging line to see room members directly

    for user_sid in room_members_snapshot:
        print(f"[DEBUG] Attempting to get session for SID {user_sid} in room '{room}'")  # Debugging line for each SID
        try:
            user_data = await sio.get_session(user_sid)
            print(f"[DEBUG] Retrieved session for SID {user_sid}: {user_data}")  # Debugging line for retrieved session
            if user_data:
                user_list.append(user_data.get('username'))
        except Exception as e:
            print(f"[ERROR] Failed to retrieve session for SID {user_sid}: {e}")  # Error handling for failed session retrieval

    print(f"[DEBUG] Emitting user list for room '{room}': {user_list}")  # Debug: Print the user list to be emitted
    await sio.emit('user_list', {'users': user_list}, room=room)

@sio.event
async def message(sid, data):
    room = data['room']
    username = data['username']
    msg = data['msg']

    # Retrieve the sender's language preference
    sender_language = user_language_preferences.get(username)

    with lock:
        # Create a snapshot of the current room members
        room_members_snapshot = deepcopy(sio.manager.rooms['/'].get(room, {}))
    
    # Send the message to the sender
    await sio.emit('message', {'msg': msg, 'username': username}, room=sid)

    print(f"[DEBUG] Users in room '{room}' (snapshot): {room_members_snapshot}")

    # Loop through all users in the room except the sender
    for user_sid in room_members_snapshot:
        if user_sid == sid:
            continue
        
        user_data = await sio.get_session(user_sid)
        user = user_data.get('username')
        user_language = user_language_preferences.get(user)

        if user_language == sender_language:
            await sio.emit('message', {'msg': msg, 'username': username}, room=user_sid)
        else:
            translated_msg = await translate_message(msg, user_language)
            await sio.emit('message', {'msg': translated_msg, 'username': username}, room=user_sid)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "chatrooms": list(active_chatrooms)})

@app.post("/chat")
async def chat(username: str = Form(...), room: str = Form(None), new_room: str = Form(None), language: str = Form(...)):
    room = new_room.strip() if new_room else room
    if not room:
        return RedirectResponse(url="/", status_code=303)
    
    active_chatrooms.add(room)
    user_language_preferences[username] = language
    
    return RedirectResponse(url=f"/chatroom?username={username}&room={room}&language={language}", status_code=303)

@app.get("/chatroom", response_class=HTMLResponse)
async def chatroom(request: Request, username: str, room: str, language: str):
    user_language_preferences[username] = language
    return templates.TemplateResponse("chat.html", {"request": request, "username": username, "room": room, "language": language})

if __name__ == "__main__":

    # Use the port provided by Heroku or default to 5000 for local development
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(socketio_app, host="0.0.0.0", port=port)

