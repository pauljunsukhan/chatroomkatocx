import os
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, join_room, leave_room, send, emit
from openai import OpenAI

app = Flask(__name__)
socketio = SocketIO(app)

# Access OpenAI API key from environment variable
api_key = os.getenv("OPENAI_API_KEY_CHATROOM")

if not api_key:
    raise ValueError("OPENAI_API_KEY_CHATROOM environment variable is not set.")

client = OpenAI(api_key=api_key)

# Store users and room information
users = {}
rooms = {}

def detect_language(text):
    """Detect language based on character presence."""
    # This is a simplistic detection method; consider using a more robust library for production
    if any("\uac00" <= char <= "\ud7a3" for char in text):  # Check for Hangul characters
        return "korean"
    return "english"

def translate_text(text, target_language):
    """Translate text using OpenAI's API based on detected language."""
    try:
        if target_language == "korean":
            prompt = f"Translate the following English text to Korean:\n\n{text}"
        else:
            prompt = f"Translate the following Korean text to English:\n\n{text}"

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )

        translation = response.choices[0].message.content.strip()
        return translation
    except Exception as e:
        return f"Error during translation: {str(e)}"

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        username = request.form['username']
        room = request.form['room']
        language = request.form['language']
        
        if room not in rooms:
            rooms[room] = []
        
        users[username] = {'room': room, 'language': language}
        return render_template('chat.html', username=username, room=room, language=language)
    
    return render_template('index.html', rooms=rooms)

@socketio.on('join')
def handle_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    send(f"{username} has joined the room {room}.", to=room)

@socketio.on('leave')
def handle_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    send(f"{username} has left the room {room}.", to=room)

@socketio.on('message')
def handle_message(data):
    msg = data['msg']
    username = data['username']
    room = data['room']
    user_language = users[username]['language']

    # Translate the message if needed for each user in the room
    for user in users:
        if users[user]['room'] == room and user != username:
            target_language = users[user]['language']
            translated_msg = translate_text(msg, target_language) if user_language != target_language else msg
            emit('message', {'msg': translated_msg, 'username': username}, room=room)
    
    # Send the original message to the sender only
    emit('message', {'msg': msg, 'username': username}, room=
