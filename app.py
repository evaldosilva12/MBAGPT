from flask import Flask, request, jsonify, render_template, session
from flask_session import Session
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
from utils import intent_classifier, semantic_search, ensure_fit_tokens, get_page_contents
from prompts import human_template, system_message
from render import user_msg_container_html_template, bot_msg_container_html_template
import openai
import streamlit as st
import os
from datetime import datetime
import glob
from flask import Flask, send_from_directory
from scrap import scrape_webpage
import time


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
pdfDB = Chroma(persist_directory=os.path.join('db', 'pdf'), embedding_function=embeddings)
pdf_retriever = pdfDB.as_retriever(search_kwargs={"k": 3})

webDB = Chroma(persist_directory=os.path.join('db', 'web'), embedding_function=embeddings)
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
    # Return the query in the appropriate message format
    return {"role": "user", "content": query}

# Function to route query to correct handler based on category
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

# Function to generate response
def generate_response():
    # Append user's query to history
    st.session_state.history.append({
        "message": st.session_state.prompt,
        "is_user": True
    })
    
    # Classify the intent
    category = intent_classifier(st.session_state.prompt)

    # Route the query based on category
    new_message = route_by_category(st.session_state.prompt, category)

    # Initialize the assistant's message variable
    assistant_message = ""

    if category == "2":
        # For category 2 (Appointment handler), set the assistant message as the buttons HTML
        assistant_message = "<button onclick='handleButton(1)'>Option 1</button><button onclick='handleButton(2)'>Option 2</button>"
    else:
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


@app.route("/bot", methods=["GET", "POST"])
def index():
    # Initialize history in session if it doesn't exist
    if 'history' not in session:
        session['history'] = []

    if request.method == "POST":
        # Append user's query to history
        session['history'].append({
            "message": request.form['prompt'],
            "is_user": True
        })

        # Initialize the assistant's message variable
        assistant_message = ""

        # Check if the prompt starts with "Appointment:"
        if request.form['prompt'].startswith("<b>Appointment:</b>"):
                time.sleep(4)
                # Get a list of all .ics files in the downloads directory
                list_of_files = glob.glob('./downloads/*.ics')
                
                # Get the most recently created file
                latest_file = max(list_of_files, key=os.path.getctime)
                
                # Now you can use 'latest_file' to do whatever you need to do
                # For example, you can send it as a download link in your response
                download_link = request.url_root + latest_file
                
                # If it does, set the assistant's message accordingly
                assistant_message = f"Hey, thanks for setting up your appointment! ✅<br><br>You can grab your appointment file (.ics) by clicking <a href='{download_link}'>here</a> 📅.<br><br>Need a hand with anything else? Just let me know!"
        else:
            # If it doesn't, proceed as before
            # Classify the intent
            category = intent_classifier(request.form['prompt'])

            if category == "2":
                # For category 2 (Appointment handler), set the assistant message as the buttons HTML
                assistant_message = "Check out our available spots for an appointment:<br><br><table><tr><th>Date</th><th>Available Hours</th></tr><tr><td>Jun 05</td><td><button id='slot1' class='button button-free' onclick='showConfirmation(\"Jun 05\", \"9am - 10am\")'>9am - 10am</button><button id='slot2' class='button occupied'>10am - 11am</button><button id='slot3' class='button occupied'>11am - 12pm</button><button id='slot4' class='button button-free' onclick='showConfirmation(\"Jun 05\", \"12pm - 1pm\")'>12pm - 1pm</button><button id='slot5' class='button button-free' onclick='showConfirmation(\"Jun 05\", \"1pm - 2pm\")'>1pm - 2pm</button><button id='slot6' class='button occupied'>2pm - 3pm</button><button id='slot7' class='button button-free' onclick='showConfirmation(\"Jun 05\", \"3pm - 4pm\")'>3pm - 4pm</button></td></tr><tr><td>Jun 06</td><td><button id='slot8' class='button occupied'>9am - 10am</button><button id='slot9' class='button occupied'>10am - 11am</button><button id='slot10' class='button occupied'>11am - 12pm</button><button id='slot11' class='button occupied'>12pm - 1pm</button><button id='slot12' class='button occupied'>1pm - 2pm</button><button id='slot13' class='button button-free' onclick='showConfirmation(\"Jun 06\", \"2pm - 3pm\")'>2pm - 3pm</button><button id='slot14' class='button button-free' onclick='showConfirmation(\"Jun 06\", \"3pm - 4pm\")'>3pm - 4pm</button></td></tr><tr><td>Jun 07</td><td><button id='slot15' class='button button-free' onclick='showConfirmation(\"Jun 07\", \"9am - 10am\")'>9am - 10am</button><button id='slot16' class='button occupied'>10am - 11am</button><button id='slot17' class='button button-free' onclick='showConfirmation(\"Jun 07\", \"11am - 12pm\")'>11am - 12pm</button><button id='slot18' class='button occupied'>12pm - 1pm</button><button id='slot19' class='button button-free' onclick='showConfirmation(\"Jun 07\", \"1pm - 2pm\")'>1pm - 2pm</button><button id='slot20' class='button occupied'>2pm - 3pm</button><button id='slot21' class='button button-free' onclick='showConfirmation(\"Jun 07\", \"3pm - 4pm\")'>3pm - 4pm</button></td></tr></table>"
            else:
                # Route the query based on category
                new_message = route_by_category(request.form['prompt'], category)

                # Construct messages from chat history
                messages = construct_messages(session['history'])

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
    return jsonify({"success": True})


@app.route('/confirm', methods=['POST'])
def confirm_appointment():
    date = request.form.get('date')  # date in 'YYYYMMDD' format
    time_start = request.form.get('time_start')  # time in 'HHMMSS' format
    time_end = request.form.get('time_end')  # time in 'HHMMSS' format

    # DTSTAMP is the current time in UTC
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Your Name//Bot Appointment//EN
BEGIN:VEVENT
UID:{dtstamp}-123400@yourdomain.com
DTSTAMP:{dtstamp}
DTSTART:{date}T{time_start}Z
DTEND:{date}T{time_end}Z
SUMMARY:Bot Appointment
DESCRIPTION:This is your bot appointment.
LOCATION:Online
END:VEVENT
END:VCALENDAR
"""
    with open(f"downloads/appointment_{date}_{time_start}.ics", 'w') as ics_file:
        ics_file.write(ics_content)
    return "Appointment confirmed and .ics file created."


@app.route('/downloads/<path:filename>')
def custom_static(filename):
    return send_from_directory('./downloads', filename)


@app.route('/scrape/<path:url>', methods=['GET'])
def scrape(url):
    try:
        result = scrape_webpage(url)
        with open('scrapped/data.txt', 'w') as f:
            f.write(result)
        return jsonify({'message': 'Scraping successful', 'data': 'Data written to file'})
    except Exception as e:
        return jsonify({'message': 'An error occurred during scraping', 'error': str(e)})

@app.route('/')
def sample():
    return render_template('sample.html')

if __name__ == "__main__":
    app.run(debug=True)