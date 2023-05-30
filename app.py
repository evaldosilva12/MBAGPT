from flask import Flask, request, jsonify, render_template, session
from flask_session import Session
from langchain.vectorstores import Chroma
from langchain.embeddings import OpenAIEmbeddings
from utils import intent_classifier, semantic_search, ensure_fit_tokens, get_page_contents
from prompts import human_template, system_message
from render import user_msg_container_html_template, bot_msg_container_html_template
import openai
import os

app = Flask(__name__)

# Set the secret key to sign the session cookie and use the filesystem session interface
app.secret_key = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

# Set OpenAI API key
openai.api_key = "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"

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
def web_handler(query):
    print("Using WEB handler...")
    # Get relevant documents from Web's database
    relevant_docs = web_retriever.get_relevant_documents(query)

    # Use the provided function to prepare the context
    context = get_page_contents(relevant_docs)

    # Prepare the prompt for GPT-3.5-turbo with the context
    query_with_context = human_template.format(query=query, context=context)

    return {"role": "user", "content": query_with_context}

def pdf_handler(query):
    print("Using PDF handler...")
    # Get relevant documents from PDF's database
    relevant_docs = pdf_retriever.get_relevant_documents(query)

    # Use the provided function to prepare the context
    context = get_page_contents(relevant_docs)

    # Prepare the prompt for GPT-3.5-turbo with the context
    query_with_context = human_template.format(query=query, context=context)

    return {"role": "user", "content": query_with_context}


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


@app.route("/", methods=["GET", "POST"])
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

        # Classify the intent
        category = intent_classifier(request.form['prompt'])

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

    return render_template("index.html", history=session['history'])

@app.route("/get_history", methods=["GET"])
def get_history():
    return jsonify({"history": session.get('history', [])})


@app.route("/clear_history", methods=["POST"])
def clear_history():
    session['history'].clear()
    session.modified = True
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True)