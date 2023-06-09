import glob
import html
import json
import os
import re
import shutil
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import openai
import streamlit as st
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template, session, redirect, send_from_directory
from flask_session import Session
from werkzeug.utils import secure_filename

from indexing import process_files, process_files_web
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from utils import intent_classifier, semantic_search, ensure_fit_tokens, get_page_contents
from prompts import human_template, system_message
from scrap import scrape_webpage


app = Flask(__name__)

# Set the secret key to sign the session cookie and use the filesystem session interface
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# Set OpenAI API key
openai.api_key = st.secrets["OPENAI_API_KEY"]

# Initialize embeddings
embeddings = OpenAIEmbeddings()

# Load the databases
pdfDB = Chroma(persist_directory=os.path.join(
    'db', 'pdf'), embedding_function=embeddings)
pdf_retriever = pdfDB.as_retriever(search_kwargs={"k": 3})

webDB = Chroma(persist_directory=os.path.join(
    'db', 'web'), embedding_function=embeddings)
web_retriever = webDB.as_retriever(search_kwargs={"k": 3})

# Initialize session history (in this case, a global variable)
history = []


# Construct messages from chat history
def construct_messages(history):
    messages = [{"role": "system", "content": system_message}]

    for entry in history:
        role = "user" if entry["is_user"] else "assistant"
        messages.append({"role": role, "content": entry["message"]})

    # Ensure total tokens do not exceed model's limit
    messages = ensure_fit_tokens(messages)

    # Print the messages
    #for message in messages:
    #    print(f"Role: {message['role']}")
    #    print(f"Content: {message['content']}")
    #    print()    

    return messages


# Define handler functions for each category
def handler(query, retriever):
    print("Using handler...")
    # Get relevant documents from the database
    relevant_docs = retriever.get_relevant_documents(query)

    # Use the provided function to prepare the context
    context = get_page_contents(relevant_docs)

    # Prepare the prompt for GPT-3.5-turbo with the context
    query_with_context = human_template.format(query=query, context=context)

    return {"role": "user", "content": query_with_context}


def web_handler(query):
    print("Using WEB handler...")
    return handler(query, web_retriever)


def pdf_handler(query):
    print("Using PDF handler...")
    return handler(query, pdf_retriever)


def appointment_handler(query):
    print("Using Appointment handler...")
    return {"role": "user", "content": query}


def other_handler(query):
    print("Using ChatGPT handler...")
    return {"role": "user", "content": query}


def route_by_category(query, category):
    if category == "0":
        return web_handler(query)
    elif category == "1":
        return pdf_handler(query)
    elif category == "2":
        return appointment_handler(query)
    elif category == "3":
        return other_handler(query)
    else:
        raise ValueError("Invalid category")


def generate_response():
    st.session_state.history.append({
        "message": st.session_state.prompt,
        "is_user": True
    })

    category = intent_classifier(st.session_state.prompt)
    new_message = route_by_category(st.session_state.prompt, category)
    assistant_message = ""

    # Construct messages from chat history
    messages = construct_messages(st.session_state.history)

    # Add the new_message to the list of messages before sending it to the API
    messages.append(new_message)

    # Ensure total tokens do not exceed model's limit
    messages = ensure_fit_tokens(messages)

    # Call the Chat Completions API with the messages
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages
    )

    # Extract the assistant's message from the response
    assistant_message = response['choices'][0]['message']['content']

    # Append assistant's message to history
    st.session_state.history.append({
        "message": assistant_message,
        "is_user": False
    })


def validate_email(email):
    if '@' in email and '.' in email:
        return True
    return False


def strip_html_tags(text):
    clean = re.compile('<.*?>')
    return html.unescape(re.sub(clean, '', text))


def send_email(to_address, chat_history):
    msg = MIMEMultipart()
    msg['From'] = 'evaldo@908eng.com'
    msg['To'] = to_address
    msg['Subject'] = 'Chat History'

    # Convert the chat history into readable strings
    chat_history_strs = [f"You: {strip_html_tags(chat_dict['message'])}" if chat_dict['is_user']
                         else f"Bot: {strip_html_tags(chat_dict['message'])}" for chat_dict in chat_history]
    body_str = '\n\n\n\n'.join(chat_history_strs)
    body = MIMEText(body_str)
    msg.attach(body)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls()
            server.login('esilva12@gmail.com', 'chzgzsiojrzhqmmv')
            server.sendmail('esilva12@gmail.com', to_address, msg.as_string())
            print('Email sent!')
    except Exception as e:
        print(f'Failed to send email: {e}')


@app.route("/bot", methods=["GET", "POST"])
def index():
    if 'history' not in session:
        session['history'] = []

    if request.method == "POST":
        session['history'].append({
            "message": request.form['prompt'],
            "is_user": True
        })

        assistant_message = ""

        def parse_date_and_time_from_message(message):
            date_pattern = r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|(?:Nov|Dec)(?:ember)?)\b \d{1,2}'
            time_pattern = r'\b(?:1[0-2]|0?[1-9]):?(?:00)?(?:am|pm)? - (?:1[0-2]|0?[1-9]):?(?:00)?(?:am|pm)?\b'

            date = re.search(date_pattern, message)
            time = re.search(time_pattern, message)

            if date is not None and time is not None:
                return date.group(), time.group()
            else:
                return None, None

        # Check if the prompt starts with ...
        if request.form['prompt'].startswith("Book appointment for "):
            date, time = parse_date_and_time_from_message(
                request.form['prompt'])
            if date is not None and time is not None:
                session['appointment_date'] = date
                session['appointment_time'] = time
                assistant_message = f"Would you like to confirm your appointment for:<br><br>📅 <b>{date}, {time}</b>?<br><br>Please type 'yes' to confirm or 'no' to cancel."
                session['confirming_appointment'] = True

        elif request.form['prompt'].lower() == 'yes' and session.get('confirming_appointment', False):
            date = session.get('appointment_date')
            time = session.get('appointment_time')
            if date is not None and time is not None:
                confirm_appointment(date, time)
                assistant_message = f"✅ Your appointment has been confirmed for <b>{date}, {time}</b>.<br><br>Could you please provide your email? I need it to send you the confirmation."
                # set session to track that we're expecting an email next
                session['asking_for_details'] = 'email'
                # We're not clearing 'confirming_appointment' yet as we're not fully done with the confirmation process.

        elif session.get('asking_for_details') == 'email':
            email = request.form['prompt']
            if validate_email(email):
                session['email'] = email
                assistant_message = "Thank you. Could you please provide your name?"
                session['asking_for_details'] = 'name'
                send_email(email, session['history'])

            else:
                promptif = request.form['prompt'].lower()
                if "no" in promptif or "cancel" in promptif:
                    assistant_message = "OK. If you don't want to provide it, just click on the Clear Chat button to start over. No worries though, your appointment is already scheduled."
                else:
                    assistant_message = "This doesn't seem to be a valid email. Could you please check and provide again?<br><br><small><i>If you don't want to provide it, just click on the Clear Chat button to start over. No worries though, your appointment is already scheduled.</i></small>"

        elif session.get('asking_for_details') == 'name':
            name = request.form['prompt']
            session['name'] = name
            assistant_message = "Thank you. I'll send the confirmation by email."
            # with the confirmation process, clear all related session variables
            session.pop('appointment_date', None)
            session.pop('appointment_time', None)
            session.pop('confirming_appointment', None)
            session.pop('asking_for_details', None)

        elif request.form['prompt'].lower() == 'no' and session.get('confirming_appointment', False):
            assistant_message = "Alright,  your appointment has not been scheduled.<br><br>If you would like to view our available time slots once more, please inform me."
            # Clear the stored appointment date and time on cancellation
            session.pop('appointment_date', None)
            session.pop('appointment_time', None)
            # Clear the confirmation tracking variable
            session.pop('confirming_appointment', None)

        else:
            # If it doesn't, proceed as before
            category = intent_classifier(request.form['prompt'])

            if category == "2":
                # For category 2 (Appointment handler), set the assistant message as the buttons HTML
                assistant_message = "Check out our available spots for an appointment:<br><br><table><tr><th>Date</th><th>Available Hours</th></tr><tr><td>Jun 12</td><td><button id='slot1' class='button button-free' onclick='bookAppointment(\"Jun 12\", \"9am - 10am\")'>9am - 10am</button><button id='slot2' class='button occupied'>10am - 11am</button><button id='slot3' class='button occupied'>11am - 12pm</button><button id='slot4' class='button button-free' onclick='bookAppointment(\"Jun 12\", \"12pm - 1pm\")'>12pm - 1pm</button><button id='slot5' class='button button-free' onclick='bookAppointment(\"Jun 12\", \"1pm - 2pm\")'>1pm - 2pm</button><button id='slot6' class='button occupied'>2pm - 3pm</button><button id='slot7' class='button button-free' onclick='bookAppointment(\"Jun 12\", \"3pm - 4pm\")'>3pm - 4pm</button></td></tr><tr><td>Jun 13</td><td><button id='slot8' class='button occupied'>9am - 10am</button><button id='slot9' class='button occupied'>10am - 11am</button><button id='slot10' class='button occupied'>11am - 12pm</button><button id='slot11' class='button occupied'>12pm - 1pm</button><button id='slot12' class='button occupied'>1pm - 2pm</button><button id='slot13' class='button button-free' onclick='bookAppointment(\"Jun 13\", \"2pm - 3pm\")'>2pm - 3pm</button><button id='slot14' class='button button-free' onclick='bookAppointment(\"Jun 13\", \"3pm - 4pm\")'>3pm - 4pm</button></td></tr><tr><td>Jun 14</td><td><button id='slot15' class='button button-free' onclick='bookAppointment(\"Jun 14\", \"9am - 10am\")'>9am - 10am</button><button id='slot16' class='button occupied'>10am - 11am</button><button id='slot17' class='button button-free' onclick='bookAppointment(\"Jun 14\", \"11am - 12pm\")'>11am - 12pm</button><button id='slot18' class='button occupied'>12pm - 1pm</button><button id='slot19' class='button button-free' onclick='bookAppointment(\"Jun 14\", \"1pm - 2pm\")'>1pm - 2pm</button><button id='slot20' class='button occupied'>2pm - 3pm</button><button id='slot21' class='button button-free' onclick='bookAppointment(\"Jun 14\", \"3pm - 4pm\")'>3pm - 4pm</button></td></tr></table>"
            else:
                new_message = route_by_category(
                    request.form['prompt'], category)
                messages = construct_messages(session['history'])
                messages.append(new_message)

                # Ensure total tokens do not exceed model's limit
                messages = ensure_fit_tokens(messages)

                # Call the Chat Completions API with the messages
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=messages
                )

                # Extract the assistant's message from the response
                assistant_message = response['choices'][0]['message']['content']

        # Append assistant's message to history
        session['history'].append({
            "message": assistant_message,
            "is_user": False
        })

        # Save changes to session
        session.modified = True

        return jsonify({"history": session['history']})

    return render_template("bot.html", history=session['history'])


@app.route("/get_history", methods=["GET"])
def get_history():
    return jsonify({"history": session.get('history', [])})


@app.route("/clear_history", methods=["POST"])
def clear_history():
    session['history'].clear()
    session.modified = True
    session.pop('appointment_date', None)
    session.pop('appointment_time', None)
    session.pop('confirming_appointment', None)
    session.pop('asking_for_details', None)
    session.pop('email', None)
    session.pop('name', None)
    return jsonify({"success": True})


def confirm_appointment(date, time):
    parsed_date = datetime.strptime(date, "%b %d").strftime(
        "%Y%m%d")  # converts "Jun 14" to "20230614"
    parsed_time_start = datetime.strptime(time.split(
        " - ")[0], "%I%p").strftime("%H%M%S")  # converts "3pm" to "150000"
    parsed_time_end = datetime.strptime(time.split(
        " - ")[1], "%I%p").strftime("%H%M%S")  # converts "4pm" to "160000"

    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Your Name//Bot Appointment//EN
BEGIN:VEVENT
UID:{dtstamp}-123400@yourdomain.com
DTSTAMP:{dtstamp}
DTSTART:{parsed_date}T{parsed_time_start}Z
DTEND:{parsed_date}T{parsed_time_end}Z
SUMMARY:Bot Appointment
DESCRIPTION:This is your bot appointment.
LOCATION:Online
END:VEVENT
END:VCALENDAR
"""
    with open(f"downloads/appointment_{parsed_date}_{parsed_time_start}.ics", 'w') as ics_file:
        ics_file.write(ics_content)
    return "Appointment confirmed and .ics file created."


@app.route('/app')
def sample():
    return render_template('services.html')


@app.route("/sucesso", methods=["GET"])
def sucesso():
    return redirect("/app")


@app.route("/", methods=["GET"])
def pin():
    return render_template("pin.html")


if __name__ == "__main__":
    app.run(debug=True)