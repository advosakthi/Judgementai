import streamlit as st
import base64
import fitz  # PyMuPDF
import google.generativeai as genai
import os
from datetime import date
import time # For potential rerun delays if needed

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Judgement Insights + AI Summary")

# --- Initialize Session State ---
# (Keep the manual entry session states as before)
if 'case_details' not in st.session_state:
    st.session_state.case_details = {
        "name": "", "number": "", "court": "", "judges": "",
        "judgement_date": None, "citations": ""
    }
if 'timeline' not in st.session_state:
    st.session_state.timeline = {
        "filing_date": None, "decision_date": None, "other_key_dates": []
    }
if 'hearings' not in st.session_state:
    st.session_state.hearings = []
if 'pdf_text' not in st.session_state:
    st.session_state.pdf_text = None
if 'summary' not in st.session_state:
    st.session_state.summary = None
if 'gemini_configured' not in st.session_state:
    st.session_state.gemini_configured = False
if 'gemini_error' not in st.session_state:
    st.session_state.gemini_error = None
if 'user_gemini_key' not in st.session_state:
     st.session_state.user_gemini_key = "" # Store user-entered key


# --- Sidebar ---
st.sidebar.title("Configuration & Upload")

# --- Gemini API Key Input ---
st.sidebar.subheader("Gemini API Key")
# Try getting key from secrets first
gemini_api_key_from_secrets = None
try:
    gemini_api_key_from_secrets = st.secrets.get("GEMINI_API_KEY")
except Exception: # Handle potential absence of secrets file/key
    pass

# Allow user to enter key if secrets key isn't found or they want to override
st.session_state.user_gemini_key = st.sidebar.text_input(
    "Enter your Gemini API Key",
    type="password",
    value=st.session_state.user_gemini_key, # Persist input within session
    help="Your key is masked and used only for this session."
)

api_key_to_use = None
key_source = None

if gemini_api_key_from_secrets:
    api_key_to_use = gemini_api_key_from_secrets
    key_source = "secrets"
    st.sidebar.success("Using Gemini API Key from Secrets.", icon="㊙️")
elif st.session_state.user_gemini_key:
    api_key_to_use = st.session_state.user_gemini_key
    key_source = "user input"
    st.sidebar.info("Using user-provided Gemini API Key.", icon="👤")
else:
    st.sidebar.warning("Gemini API Key needed for AI features.")
    st.session_state.gemini_configured = False # Ensure it's false if no key

# --- Configure Gemini API (only if a key is available and not already configured/failed) ---
gemini_model = None
if api_key_to_use and not st.session_state.gemini_configured and st.session_state.gemini_error is None:
    try:
        with st.spinner("Configuring Gemini API..."):
            genai.configure(api_key=api_key_to_use)
            # Test with a simple list_models call (optional but good check)
            # models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # if not models:
            #     raise ValueError("No suitable generative models found with this API key.")

            # Initialize the model
            #gemini_model = genai.GenerativeModel('gemini-pro') # Or 'gemini-1.5-flash'
            # New: Use a current, recommended model
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            st.session_state.gemini_configured = True
            st.session_state.gemini_error = None # Clear previous error on success
            # st.sidebar.success(f"Gemini configured using key from {key_source}.") # Optional success msg
            # time.sleep(1) # Brief pause
            # st.experimental_rerun() # Rerun may help update state cleanly sometimes
    except Exception as e:
        st.sidebar.error(f"Failed to configure Gemini: {e}")
        st.session_state.gemini_configured = False
        st.session_state.gemini_error = str(e) # Store error message

# Display persistent error if configuration failed
elif st.session_state.gemini_error:
     st.sidebar.error(f"Gemini Config Error: {st.session_state.gemini_error}")


# --- File Upload ---
st.sidebar.subheader("Upload Judgement")
uploaded_file = st.sidebar.file_uploader("Choose a PDF file", type="pdf", key="pdf_uploader")


# --- Helper Functions (Keep display_pdf, extract_text_from_pdf as before) ---
def display_pdf(uploaded_file):
    """Displays the uploaded PDF file in an embed tag."""
    bytes_data = uploaded_file.getvalue()
    base64_pdf = base64.b64encode(bytes_data).decode("utf-8")
    pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf">'
    st.markdown(pdf_display, unsafe_allow_html=True)

def extract_text_from_pdf(uploaded_file):
    """Extracts text from the uploaded PDF file using PyMuPDF."""
    try:
        uploaded_file.seek(0)
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = ""
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}")
        return None

def summarize_with_gemini(text_to_summarize, model):
    """Generates a summary using the provided Gemini model instance."""
    if not st.session_state.gemini_configured or model is None:
        return "❌ Gemini API not configured or model unavailable."

    prompt = f"""
    Please provide a concise executive summary of the following legal judgement text. Focus on:
    1. The main issue(s) decided.
    2. The core reasoning of the court.
    3. The final verdict or outcome.
    Keep the summary clear and objective, suitable for a legal professional. Max 3-4 paragraphs.

    Text to summarize:
    ---
    {text_to_summarize[:30000]} # Limit text length if needed to avoid token limits
    ---
    Summary:
    """
    try:
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        response = model.generate_content(prompt, safety_settings=safety_settings)

        if response.parts:
             return response.text
        else:
             block_reason = response.prompt_feedback.block_reason if response.prompt_feedback else "Unknown"
             st.error(f"Summary generation failed or was blocked. Reason: {block_reason}. ...", icon="🚫") 
             return None # Return None explicitly on failure/block

    except Exception as e:
        st.error(f"Gemini API Error during generation: {e}", icon="🔥") 
        return None # Return None on API error


# --- Main App Area ---
st.title("🏛️ Judgement Insights with AI Summary")
st.write("Upload a judgement PDF, enter API key (if not using secrets), generate AI summary, and manually enter details.")

if uploaded_file is not None:
    # Process PDF only once per upload
    if st.session_state.pdf_text is None or uploaded_file.file_id != st.session_state.get('uploaded_file_id', None):
         with st.spinner("Extracting text from PDF..."):
            st.session_state.pdf_text = extract_text_from_pdf(uploaded_file)
            st.session_state.summary = None # Reset summary if new file
            st.session_state.uploaded_file_id = uploaded_file.file_id # Track file id
            if st.session_state.pdf_text:
                st.sidebar.success("PDF text extracted.", icon="📄")
            else:
                st.sidebar.error("Failed to extract text.")

    # --- Layout: PDF Viewer and Data Entry/Summary Side-by-Side ---
    col1, col2 = st.columns([2, 1])

    with col1:
        st.header("📄 Judgement PDF")
        display_pdf(uploaded_file)

    with col2:
        st.header("📊 Analysis & Details")

        # --- AI Summary Section ---
        st.subheader("🤖 AI Executive Summary")
        # Enable button only if Gemini is configured AND text is available
        if st.session_state.gemini_configured and st.session_state.pdf_text:
            if st.button("Generate Summary with Gemini"):
                # Re-initialize model just in case state was lost (though session state should hold config status)
                if api_key_to_use: # Redundant check, but safe
                     try:
                          if not gemini_model: # Try to re-initialize if None
                              genai.configure(api_key=api_key_to_use)
                              #gemini_model = genai.GenerativeModel('gemini-pro')
                              gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
                              

                          if gemini_model: # Check again after potential re-init
                               with st.spinner("✨ Generating summary... Please wait."):
                                  summary_result = summarize_with_gemini(st.session_state.pdf_text, gemini_model)
                                  if summary_result: # Check if summarization succeeded
                                       st.session_state.summary = summary_result
                                  # Error messages handled within summarize_with_gemini

                     except Exception as e:
                          st.error(f"Error during summary generation setup: {e}")
                          st.session_state.summary = None # Ensure summary is None on error
                else:
                     st.warning("Cannot generate summary - API key issue.")


            if st.session_state.summary:
                st.markdown("**Generated Summary:**")
                st.markdown(f"> {st.session_state.summary}", unsafe_allow_html=True)
                st.markdown("---")
            # Button is only shown if configured, so only need else for initial state
            elif not st.session_state.summary and st.session_state.pdf_text:
                 st.info("Click the button above to generate an AI summary.")


        elif not st.session_state.gemini_configured:
            st.warning("Gemini API not configured. Enter a valid API Key in the sidebar.", icon="🔑")
        elif not st.session_state.pdf_text:
             st.warning("Could not extract text from PDF. Summary generation unavailable.", icon="📄")


        # --- Manual Entry Sections (Collapsible) ---
        st.subheader("📝 Manual Entry")
        with st.expander("Case Details (Manual)", expanded=False):
             # (Keep the manual case details input fields)
            st.session_state.case_details['name'] = st.text_input("Case Name", value=st.session_state.case_details.get('name', ''), key="case_name")
            st.session_state.case_details['number'] = st.text_input("Case Number", value=st.session_state.case_details.get('number', ''), key="case_number")
            st.session_state.case_details['court'] = st.text_input("Court", value=st.session_state.case_details.get('court', ''), key="case_court")
            st.session_state.case_details['judges'] = st.text_input("Judge(s)", value=st.session_state.case_details.get('judges', ''), key="case_judges")
            st.session_state.case_details['judgement_date'] = st.date_input("Date of Judgement", value=st.session_state.case_details.get('judgement_date', None), key="case_judgement_date")
            st.session_state.case_details['citations'] = st.text_area("Relevant Citations", value=st.session_state.case_details.get('citations', ''), height=100, key="case_citations")


        with st.expander("Key Timeline Dates (Manual)", expanded=False):
            # (Keep the manual timeline input fields)
             filing_date_val = st.session_state.timeline.get('filing_date', None)
             decision_date_val = st.session_state.timeline.get('decision_date', st.session_state.case_details.get('judgement_date', None))
             st.session_state.timeline['filing_date'] = st.date_input("Case Filing Date", value=filing_date_val, key="timeline_filing")
             st.session_state.timeline['decision_date'] = st.date_input("Final Decision Date", value=decision_date_val, key="timeline_decision")


        with st.expander("Hearing Summaries (Manual)", expanded=False):
            # (Keep the manual hearing summary input logic)
            st.subheader("Add New Hearing")
            new_hearing_date = st.date_input("Hearing Date", key="new_hearing_date_input_ai")
            new_hearing_summary = st.text_area("Hearing Summary/Key Points", height=150, key="new_hearing_summary_input_ai")

            if st.button("Add Hearing Summary", key="add_hearing_btn_ai"):
                if new_hearing_date and new_hearing_summary:
                    # Append to list, ensuring list exists
                    if 'hearings' not in st.session_state: st.session_state.hearings = []
                    st.session_state.hearings.append({"date": new_hearing_date, "summary": new_hearing_summary})
                    st.success(f"Added hearing for {new_hearing_date.strftime('%Y-%m-%d')}")
                else:
                    st.warning("Please provide both date and summary for the hearing.")

            st.subheader("Recorded Hearings")
            if not st.session_state.hearings:
                st.info("No hearing summaries added yet.")
            else:
                try:
                    # Defensive sort: handle potential None dates if input allows
                    sorted_hearings = sorted([h for h in st.session_state.hearings if h.get('date')], key=lambda x: x['date'])
                    for i, hearing in enumerate(sorted_hearings):
                        with st.container():
                            st.markdown(f"**{i+1}. Date:** {hearing['date'].strftime('%Y-%m-%d')}")
                            st.markdown("**Summary:**")
                            st.caption(f"> {hearing.get('summary', 'N/A')}") # Use .get for safety
                            st.markdown("---")
                except Exception as e:
                     st.error(f"Error displaying hearings: {e}") # Catch potential sort/display errors


    # --- Optional: Display Entered Data Summary ---
    # ... (keep if desired) ...


else:
    st.info("☝️ Upload a PDF file using the sidebar to get started.")
    # Clear relevant state if no file is uploaded
    st.session_state.pdf_text = None
    st.session_state.summary = None
    st.session_state.uploaded_file_id = None
    # Don't clear API key config state here, allow it to persist