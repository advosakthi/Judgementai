import streamlit as st
import base64
import fitz  # PyMuPDF
import google.generativeai as genai
import os
from datetime import date
from streamlit_pdf_viewer import pdf_viewer # Import the component
import time # For potential rerun delays if needed

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Hon'ble Mr. Justice A.D. Jagadish Chandira")

# --- Initialize Session State ---
# Ensure all keys are initialized to prevent errors on first run
default_session_state = {
    "case_details": {"name": "", "number": "", "court": "", "judges": "", "judgement_date": None, "citations": ""},
    "timeline": {"filing_date": None, "decision_date": None, "other_key_dates": []},
    "hearings": [],
    "pdf_text": None,
    "summary": None,
    "gemini_configured": False,
    "gemini_error": None,
    "user_gemini_key": "",
    "uploaded_file_id": None,
}
for key, default_value in default_session_state.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# --- Sidebar ---
st.sidebar.title("Configuration & Upload")

# --- Gemini API Key Input ---
st.sidebar.subheader("Gemini API Key")
gemini_api_key_from_secrets = None
try:
    # Attempt to get key from Streamlit secrets (if deployed with secrets)
    gemini_api_key_from_secrets = st.secrets.get("GEMINI_API_KEY")
except Exception:
    pass # Handle cases where secrets aren't available locally or not set

# Allow user to enter key if secrets key isn't found or they want to override
st.session_state.user_gemini_key = st.sidebar.text_input(
    "Enter your Gemini API Key",
    type="password",
    value=st.session_state.user_gemini_key,
    help="Your key is masked and used only for this session. Secrets key (if available) takes precedence.",
    key="gemini_key_input" # Add unique key
)

api_key_to_use = None
key_source = None
gemini_model = None # Initialize model variable outside the config block

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
# This block attempts configuration if needed
if api_key_to_use and not st.session_state.gemini_configured and st.session_state.gemini_error is None:
    try:
        with st.spinner("Configuring Gemini API..."):
            genai.configure(api_key=api_key_to_use)
            # Use a current, recommended model like gemini-1.5-flash-latest
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            # You could add a quick test here like list_models if needed
            st.session_state.gemini_configured = True
            st.session_state.gemini_error = None # Clear previous error on success
            # st.sidebar.success(f"Gemini configured using key from {key_source}.") # Optional success msg
    except Exception as e:
        st.sidebar.error(f"Failed to configure Gemini: {e}")
        st.session_state.gemini_configured = False
        st.session_state.gemini_error = str(e) # Store error message
        gemini_model = None # Ensure model is None on error

# Re-fetch model instance if already configured (handles reruns better)
elif st.session_state.gemini_configured and api_key_to_use:
     try:
          # Re-initialize model instance if needed (e.g., after script rerun)
          genai.configure(api_key=api_key_to_use) # Re-configure might be needed
          gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
     except Exception as e:
          st.sidebar.error(f"Re-configuring Gemini failed: {e}")
          st.session_state.gemini_configured = False
          st.session_state.gemini_error = str(e)
          gemini_model = None

# Display persistent error if configuration failed previously
elif st.session_state.gemini_error:
     st.sidebar.error(f"Gemini Config Error: {st.session_state.gemini_error}")


# --- File Upload ---
st.sidebar.subheader("Upload Judgement")
uploaded_file = st.sidebar.file_uploader(
    "Choose a PDF file",
    type="pdf",
    key="pdf_uploader",
    # Clear previous state if file is removed
    on_change=lambda: (
        st.session_state.update({
            "pdf_text": None,
            "summary": None,
            "uploaded_file_id": None
        })
    ) if st.session_state.pdf_uploader is None else None
)


# --- Helper Functions ---
def extract_text_from_pdf(file_bytes):
    """Extracts text from PDF bytes using PyMuPDF."""
    try:
        # Open the PDF file from bytes
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            text = ""
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text += page.get_text()
        return text
    except Exception as e:
        st.error(f"Error extracting text from PDF: {e}", icon="📄")
        return None

def summarize_with_gemini(text_to_summarize, model):
    """Generates a summary using the provided Gemini model instance."""
    if not st.session_state.gemini_configured or model is None:
        st.warning("Gemini not configured. Cannot summarize.", icon="⚠️")
        return None # Return None if not configured

    # Basic check for text length
    if not text_to_summarize or len(text_to_summarize) < 50: # Arbitrary short length
         st.warning("Not enough text extracted from PDF to summarize effectively.", icon="⚠️")
         return None

    # Limit input text length to avoid exceeding token limits (adjust as needed)
    # Gemini 1.5 Flash has a large context window, but it's still good practice
    max_chars = 100000 # Example limit, adjust based on model and typical document size
    truncated_text = text_to_summarize[:max_chars]
    if len(text_to_summarize) > max_chars:
        st.info(f"Summarizing the first {max_chars} characters due to length limit.", icon="ℹ️")


    prompt = f"""
    Please provide a concise executive summary of the following legal judgement text. Focus specifically on:
    1.  The primary legal question(s) or issue(s) the court addressed.
    2.  The court's main conclusion or holding on those issues.
    3.  The core legal reasoning or principles applied by the court to reach the conclusion.
    4.  The final disposition or outcome of the case (e.g., affirmed, reversed, remanded).

    Keep the summary objective, factual, and suitable for a legal professional who needs a quick understanding of the case's essence. Avoid opinions or interpretations not explicitly stated in the text. Use clear and precise legal language where appropriate. Aim for 3-5 paragraphs.

    Text to summarize:
    ---
    {truncated_text}
    ---
    Summary:
    """
    try:
        # Safety settings (adjust thresholds if needed)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]
        # Generation configuration (optional, e.g., temperature for creativity)
        # generation_config = genai.types.GenerationConfig(temperature=0.3)

        response = model.generate_content(
             prompt,
             safety_settings=safety_settings,
             # generation_config=generation_config
             )

        # Check response for content and potential blocks
        if response.parts:
             return response.text
        else:
             block_reason = "Unknown"
             safety_ratings = "N/A"
             try: # Safely access feedback attributes
                 if response.prompt_feedback:
                      block_reason = response.prompt_feedback.block_reason or "Not specified"
                 if response.candidates and response.candidates[0].safety_ratings:
                      safety_ratings = response.candidates[0].safety_ratings
             except Exception:
                 pass # Ignore errors accessing feedback details
             st.error(f"Summary generation failed or was blocked. Reason: {block_reason}. Safety Ratings: {safety_ratings}", icon="🚫")
             return None

    except Exception as e:
        st.error(f"Gemini API Error during generation: {e}", icon="🔥")
        # Attempt to provide more specific error info if available
        if "API key not valid" in str(e):
            st.error("Please check if your Gemini API Key is correct and active.", icon="🔑")
        elif "quota" in str(e).lower():
             st.error("You may have exceeded your Gemini API quota.", icon=" R📊")
        return None


# --- Main App Area ---
st.title("🏛️ Judgement Insights with AI Summary")
st.write("Upload a judgement PDF, enter API key (if needed), generate AI summary, and manually enter details.")

if uploaded_file is not None:
    current_file_id = uploaded_file.file_id

    # Process PDF text only once per new file upload
    if st.session_state.pdf_text is None or current_file_id != st.session_state.uploaded_file_id:
        with st.spinner("Reading and extracting text from PDF..."):
            uploaded_file.seek(0) # Reset buffer before reading
            pdf_bytes_for_text = uploaded_file.read()
            st.session_state.pdf_text = extract_text_from_pdf(pdf_bytes_for_text)
            st.session_state.summary = None # Reset summary for new file
            st.session_state.uploaded_file_id = current_file_id # Track file id
            if st.session_state.pdf_text:
                st.sidebar.success(f"PDF text extracted ({len(st.session_state.pdf_text):,} chars).", icon="📄")
            else:
                st.sidebar.error("Failed to extract text. Cannot generate summary.", icon="⚠️")

    # --- Layout: PDF Viewer and Data Entry/Summary Side-by-Side ---
    col1, col2 = st.columns([3, 2]) # Adjust ratio if needed

    with col1:
        st.header("📄 Judgement PDF Viewer")
        try:
            uploaded_file.seek(0) # Ensure buffer is at the start for viewer
            pdf_bytes_for_viewer = uploaded_file.read()
            with st.container(): # Use container to control height better if needed
                 pdf_viewer(input=pdf_bytes_for_viewer, width=700, height=800) # Use the component
        except Exception as e:
            st.error(f"Could not display PDF viewer: {e}", icon=" R🖼️")


    with col2:
        st.header("📊 Analysis & Details")

        # --- AI Summary Section ---
        st.subheader("🤖 AI Executive Summary")
        # Enable button only if Gemini is configured AND text extraction was successful
        summarize_button_disabled = not st.session_state.gemini_configured or not st.session_state.pdf_text
        summarize_help_text = "Gemini API not configured or PDF text not extracted." if summarize_button_disabled else None

        if st.button("Generate Summary with Gemini", disabled=summarize_button_disabled, help=summarize_help_text):
            # Check again right before calling, model instance might be lost on rerun
            if gemini_model and st.session_state.pdf_text:
                 with st.spinner("✨ Generating summary... Please wait."):
                     summary_result = summarize_with_gemini(st.session_state.pdf_text, gemini_model)
                     # Only update state if summarization returned text
                     if summary_result:
                          st.session_state.summary = summary_result
                     else:
                          # Keep existing summary if generation failed, or clear it
                          # st.session_state.summary = None # Option to clear on failure
                          st.warning("Summary generation failed. Please check errors above.", icon="⚠️")
            elif not st.session_state.pdf_text:
                 st.warning("Cannot generate summary - PDF text missing.", icon="📄")
            else: # Should only happen if config failed between page load and button click
                 st.error("Cannot generate summary - Gemini configuration issue.", icon="⚙️")


        # Display Summary or Messages
        if st.session_state.summary:
            st.markdown("**Generated Summary:**")
            st.markdown(f"> {st.session_state.summary}", unsafe_allow_html=True) # Display summary
            st.markdown("---") # Separator
        elif summarize_button_disabled and st.session_state.gemini_error:
             st.warning(f"Cannot generate summary. Fix API configuration error in sidebar: {st.session_state.gemini_error}", icon="🔑")
        elif summarize_button_disabled and not st.session_state.pdf_text and uploaded_file:
             st.warning("Cannot generate summary because text extraction failed.", icon="📄")
        elif summarize_button_disabled:
             st.info("Configure Gemini API and upload a valid PDF to enable summary generation.", icon="💡")
        # If button is enabled but no summary yet
        elif not summarize_button_disabled and not st.session_state.summary:
             st.info("Click the button above to generate an AI summary.", icon="🤖")


        # --- Manual Entry Sections (Collapsible) ---
        st.subheader("📝 Manual Entry")
        with st.expander("Case Details (Manual)", expanded=False):
            st.session_state.case_details['name'] = st.text_input("Case Name", value=st.session_state.case_details.get('name', ''), key="case_name")
            st.session_state.case_details['number'] = st.text_input("Case Number", value=st.session_state.case_details.get('number', ''), key="case_number")
            st.session_state.case_details['court'] = st.text_input("Court", value=st.session_state.case_details.get('court', ''), key="case_court")
            st.session_state.case_details['judges'] = st.text_input("Judge(s)", value=st.session_state.case_details.get('judges', ''), key="case_judges")
            st.session_state.case_details['judgement_date'] = st.date_input("Date of Judgement", value=st.session_state.case_details.get('judgement_date', None), key="case_judgement_date")
            st.session_state.case_details['citations'] = st.text_area("Relevant Citations", value=st.session_state.case_details.get('citations', ''), height=100, key="case_citations")


        with st.expander("Key Timeline Dates (Manual)", expanded=False):
             # Default decision date to judgement date if available
             default_decision_date = st.session_state.case_details.get('judgement_date', None)
             timeline_decision_date = st.session_state.timeline.get('decision_date', default_decision_date)

             st.session_state.timeline['filing_date'] = st.date_input("Case Filing Date", value=st.session_state.timeline.get('filing_date', None), key="timeline_filing")
             st.session_state.timeline['decision_date'] = st.date_input("Final Decision Date", value=timeline_decision_date, key="timeline_decision")


        with st.expander("Hearing Summaries (Manual)", expanded=False):
            st.subheader("Add New Hearing")
            # Use unique keys to prevent state issues if multiple forms exist
            new_hearing_date = st.date_input("Hearing Date", key="new_hearing_date")
            new_hearing_summary = st.text_area("Hearing Summary/Key Points", height=150, key="new_hearing_summary")

            if st.button("Add Hearing Summary", key="add_hearing_btn"):
                if new_hearing_date and new_hearing_summary:
                    # Ensure list exists before appending
                    if 'hearings' not in st.session_state or not isinstance(st.session_state.hearings, list):
                        st.session_state.hearings = []
                    st.session_state.hearings.append({"date": new_hearing_date, "summary": new_hearing_summary})
                    st.success(f"Added hearing for {new_hearing_date.strftime('%Y-%m-%d')}")
                    # Clear inputs by resetting their default values (requires rerun or more complex state)
                    # For simplicity, manual clearing or persistence might be acceptable.
                else:
                    st.warning("Please provide both date and summary for the hearing.")

            st.subheader("Recorded Hearings")
            if not st.session_state.hearings:
                st.info("No hearing summaries added yet.")
            else:
                try:
                    # Defensive sort: handle potential None dates and ensure list structure
                    valid_hearings = [h for h in st.session_state.hearings if isinstance(h, dict) and h.get('date')]
                    sorted_hearings = sorted(valid_hearings, key=lambda x: x['date'])
                    for i, hearing in enumerate(sorted_hearings):
                        with st.container(): # Use container for better layout control
                            st.markdown(f"**{i+1}. Date:** {hearing['date'].strftime('%Y-%m-%d')}")
                            st.markdown("**Summary:**")
                            # Use .get for safe access to summary key
                            st.caption(f"> {hearing.get('summary', 'N/A')}")
                            st.markdown("---")
                except Exception as e:
                     st.error(f"Error displaying hearings: {e}", icon=" R⚠️")


    # --- Optional: Display Entered Data Summary (Below the columns) ---
    # You can add a section here to display st.session_state.case_details, etc. in tables
    # st.markdown("---")
    # st.header("📋 Summary of Manually Entered Information")
    # ...


else:
    st.info("☝️ Upload a PDF file using the sidebar to get started.")
    # Optionally clear specific state when no file is loaded, but keep API key info
    # st.session_state.pdf_text = None
    # st.session_state.summary = None
    # st.session_state.uploaded_file_id = None
    # st.session_state.hearings = [] # Clear hearings if needed
    # st.session_state.case_details = default_session_state["case_details"] # Reset details
    # st.session_state.timeline = default_session_state["timeline"] # Reset timeline