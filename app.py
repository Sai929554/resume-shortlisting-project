import streamlit as st
import imaplib
import email
from email.header import decode_header
import pandas as pd
from docx import Document
from PyPDF2 import PdfReader
import re
import io
import spacy
import time
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity

nlp = spacy.load("en_core_web_sm")

# Email credentials
EMAIL_USER = "k12392945@gmail.com"  # Replace with your email
EMAIL_PASS = "xcya gowp wxrd cjav"  # Replace with your app password

# Sanitize filenames (remove problematic characters)
def sanitize_filename(filename):
    if not filename:  # Check if filename is None or empty
        return "unknown_filename"
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    sanitized = sanitized.replace('\r', '').replace('\n', '').replace('\t', '')
    return sanitized

# Extract email body
def extract_email_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" not in content_disposition:
                if content_type == "text/plain":
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")
                elif content_type == "text/html":
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")
    else:
        return msg.get_payload(decode=True).decode("utf-8", errors="ignore")

# Extract text from DOCX
def extract_text_from_docx(attachment_content):
    doc = Document(io.BytesIO(attachment_content))
    full_text = [para.text for para in doc.paragraphs]
    return '\n'.join(full_text)

# Extract text from PDF
def extract_text_from_pdf(attachment_content):
    pdf_reader = PdfReader(io.BytesIO(attachment_content))
    text = "".join(page.extract_text() for page in pdf_reader.pages)
    return text

# Extract resume details
def extract_name_from_text(text):
    text = text.strip()
    text = re.sub(r'\S+@\S+', '', text)
    text = re.sub(r'[^a-zA-Z\s]', '', text)
    lines = text.split("\n")
    irrelevant_words = ["summary", "contact", "education", "experience", "skills", "references", "profile", "resume", "cv"]
    for line in lines[:3]:
        line = line.strip()
        if any(irrelevant_word in line.lower() for irrelevant_word in irrelevant_words):
            continue
        if len(line) > 1:
            name_parts = line.split()
            if len(name_parts) > 1:
                return " ".join([part.title() for part in name_parts])
            elif len(name_parts) == 1:
                return name_parts[0].title()
    return "Name not found"

# Function to extract email from resume text
def extract_email_from_text(text):
    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return email_match.group(0) if email_match else "Email not found"

# Function to extract phone numbers
def extract_phone_from_text(text):
    phone_pattern = re.compile(r"(?:direct|mobile|phone|ph#|contact|tel|cell)?[:\s-]*"
                               r"(?:\+?\d{1,3}[-.\s]?)?"
                               r"\(?\d{1,4}\)?"
                               r"[-.\s]?\d{1,4}"
                               r"[-.\s]?\d{1,4}"
                               r"[-.\s]?\d{1,9}"
                               r"(?:\s?(?:ext|x|extension)\s?\d{1,5})?")
    matches = phone_pattern.findall(text)
    phones = [re.sub(r"[^+\d\s()-]", "", match).strip() for match in matches if len(re.sub(r"\D", "", match)) >= 10]
    return ", ".join(phones) if phones else "Phone not found"

# Function to extract experience from resume text
def extract_experience(text):
    text = text.lower()
    numeric_pattern = r"(?:more than|over|at least|around|approximately|nearly|up to)?\s*(\d+)\+?\s*years?"
    numeric_match = re.search(numeric_pattern, text)
    if numeric_match:
        years = numeric_match.group(1)
        return f"{int(years)}+ years" if '+' in numeric_match.group(0) else f"{int(years)} years"
    return "Experience not found"

# Function to extract certifications
def extract_certifications_count(text):
    certification_keywords = [
        r"certification", r"certifications", r"certified", r"certificate", r"certificates"
    ]
    pattern = r"|".join(certification_keywords)
    matches = re.findall(pattern, text, re.IGNORECASE)
    return len(matches)

# Function to extract location from resume text
def extract_location_from_text(text):
    location_match = re.search(
        r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s(?:TX|CA|NY|FL|WA|IL|PA|GA|NC|OH|NJ|VA|CO|AZ|MA|MD|TN|MO|IN|WI|MN|SC|AL|LA|KY|OR|OK|CT|IA|MS|KS|AR|NV|UT|NM|NE|WV|ID|HI|ME|NH|MT|RI|DE|SD|ND|AK|VT|WY))\b"  # City, State
        r"|\b\d{5}(?:-\d{4})?\b",  # ZIP code
        text
    )
    if location_match:
        location = location_match.group(0)
        if not any(keyword in location.lower() for keyword in ["assistant", "server", "sql"]):  # Example of filtering out unrelated matches
            return location
    return "Location not found"

# Extract government from resume text
def extract_government_details(text):
    patterns = [
        r"(Client:.*?Present|Client:.*?\d{4}|Client:.*?Till Date)",  # Client and its timeframe
        r"(Professional Experience:.*?Present|Professional Experience:.*?\d{4}|Professional Experience:.*?Till Date)",
        r"(EXPERIENCE.*?Present|EXPERIENCE.*?\d{4}|EXPERIENCE.*?Till Date)",
        r"(Past work:.*?Present|Past work:.*?\d{4}|Past work:.*?Till Date)",
        r"(WORK EXPERIENCE:.*?Present|WORK EXPERIENCE:.*?\d{4}|WORK EXPERIENCE:.*?Till Date)",
    ]
   
    extracted_sections = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        extracted_sections.extend(matches)
   
    combined_text = " ".join(extracted_sections)
   
    location_pattern = re.compile(
        r"""
        (?:Client:\s*)?                                      # Optional 'Client:' prefix
        ([A-Za-z\s,.()]+(?:USA|México|Virginia|FL|NJ|Texas|Tallahassee|Reston|New York|U\.S\.A\.|U\.S\.|America))  # Location
        .*?                                                  # Any text in between
        (?=\s*(?:Present|Till Date|to date|current|\d{4}[-–]\d{4}|[\w\s]+))  # Lookahead for keywords or date patterns
       
        |  # OR
       
        Client:\s*                                            # 'Client:' prefix
        ([A-Za-z\s,]+)                                        # Location
        \s+[A-Z][a-z]+\s\d{4}\s*[-—]\s*Present                # Date range ending with 'Present'
        """,
        re.IGNORECASE | re.VERBOSE
    )
   
    match = location_pattern.search(combined_text)
   
    if match:
        first_location = match.group(0).strip()
        cleaned_location = re.sub(r"(Client:|Present|EXPERIENCE|Past work:|WORK EXPERIENCE:|\d{4}[-–]\d{4}|[A-Za-z]+\s\d{4}\s*[-—]\s*Present|[\t\n]+)", "", first_location)
        cleaned_location = re.sub(r"\s{2,}", " ", cleaned_location).strip()  # Remove extra spaces
        formatted_location = f"[{cleaned_location}]"
        return formatted_location
    else:
        return "Not found"

# Function to extract visa status from the resume text
def extract_visa_status(text):
    visa_keywords = {
        "H1B": ["h1b"],
        "Green Card": ["green card", "permanent resident"],
        "US Citizen": ["usc", "us citizen", "citizenship: us"],
        "OPT": ["opt"],
        "CPT": ["cpt"],
        "L2": ["l2 visa"],
        "EAD": ["ead"],
        "TN Visa": ["tn visa"],
        "Study Visa": ["study visa"]
    }
    visa_status = []
    for visa, patterns in visa_keywords.items():
        for pattern in patterns:
            if re.search(pattern, text.lower()):
                visa_status.append(visa)
                break
    return ", ".join(visa_status) if visa_status else "Not found"

def extract_relevant_skills(resume_text, job_desc_text, predefined_skills=None):
    """
    Extracts all possible skills from a resume using multiple strategies and returns those relevant to the job description.
    
    :param resume_text: The full text of the resume.
    :param job_desc_text: The job description text.
    :param predefined_skills: An optional set of predefined skills to match against.
    :return: List of relevant skills found in the resume.
    """
    resume_text = resume_text.lower()
    job_desc_text = job_desc_text.lower()
    
    # Tokenize job description and create a set of keywords
    job_desc_words = {token.text for token in nlp(job_desc_text) if not token.is_stop and not token.is_punct}
    
    # Extract skills from a dedicated "Skills" section
    skills_section_match = re.search(
        r"(?:skills|technical skills|competencies|technologies)[:\s]*(.*?)(?:\n\n|\n[A-Z]|\Z)",
        resume_text, re.DOTALL
    )
    skills_section = skills_section_match.group(1).strip() if skills_section_match else ""
    extracted_skills = {skill.strip() for skill in re.split(r"[\n,;]", skills_section) if skill.strip()}

    # Extract skills based on contextual phrases
    context_skills = set()
    for match in re.findall(r"(?:proficient in|experienced with|skilled in|knowledge of|familiar with)\s+([a-zA-Z0-9\s+\-]+)", resume_text):
        context_skills.update(map(str.strip, match.split(",")))

    # Extract skills using Named Entity Recognition (NER)
    doc = nlp(resume_text)
    ner_skills = {ent.text.strip() for ent in doc.ents if ent.label_ in {"PRODUCT", "ORG", "WORK_OF_ART", "FACILITY"}}
    
    # Extract common technology-related terms
    tech_keywords = re.findall(r"\b[A-Za-z0-9+\-#\.]+\b", resume_text)
    tech_skills = {word for word in tech_keywords if word.isalpha() and len(word) > 1}
    
    # Combine all extracted skills
    all_skills = extracted_skills.union(context_skills, ner_skills, tech_skills)
    
    # If a predefined skills list is provided, filter only those skills
    if predefined_skills:
        all_skills = {skill for skill in all_skills if skill.lower() in predefined_skills}

    # Extract only relevant skills by matching with job description keywords
    relevant_skills = all_skills.intersection(job_desc_words)

    return list(relevant_skills) if relevant_skills else list(all_skills)  # Return all skills if no match with JD

def calculate_resume_score(resume_text, job_desc_text, skills, experience, certifications, visa_status, location):
    corpus = [job_desc_text, resume_text]
    vectorizer = CountVectorizer().fit_transform(corpus)
    vectors = vectorizer.toarray()

    similarity_score = cosine_similarity([vectors[0]], [vectors[1]])[0][0]

    skills_count = len(skills)
    experience_years = int(re.search(r"\d+", experience).group(0)) if re.search(r"\d+", experience) else 0
    certifications_count = certifications

    normalized_experience = min(experience_years / 20, 1)
    normalized_skills = min(skills_count / 20, 1)

    visa_priority = {
        "US Citizen": 1.0,
        "Green Card": 0.9,
        "H1B": 0.8,
        "OPT": 0.7,
        "CPT": 0.6,
        "L2": 0.5,
        "EAD": 0.5,
        "TN Visa": 0.6,
        "Study Visa": 0.4,
        "Not found": 0.0
    }
    visa_score = visa_priority.get(visa_status, 0.0)

    location_score = 0.0
    if location.lower() != "location not found":
        location_score = 1.0

    score = (
        similarity_score * 0.4 +
        normalized_skills * 0.25 +
        normalized_experience * 0.25 +
        certifications_count * 0.2 +
        visa_score * 0.05 +
        location_score * 0.05
    )

    return round(min(score * 100, 100), 2)

def filter_emails_by_job_id(job_id, email_ids, mail):
    filtered_emails = []
    for email_id in email_ids:
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8")
                if job_id.lower() in subject.lower():
                    filtered_emails.append(msg)
                else:
                    body = extract_email_body(msg)
                    if body and job_id.lower() in body.lower():
                        filtered_emails.append(msg)
    return filtered_emails

def process_resumes_and_attachments(job_id):
    mail = imaplib.IMAP4_SSL('imap.gmail.com')
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    print(f"Processing emails for Job ID: {job_id}")
    status, messages = mail.search(None, 'ALL')
    email_ids = messages[0].split()

    filtered_emails = filter_emails_by_job_id(job_id, email_ids, mail)
    print(f"Found {len(filtered_emails)} emails matching the Job ID: {job_id}")

    resume_details = []

    for msg in filtered_emails:
        job_desc_text = extract_email_body(msg)

        for part in msg.walk():
            if part.get("Content-Disposition") and "attachment" in part.get("Content-Disposition"):
                attachment_filename = sanitize_filename(part.get_filename())
                attachment_content = part.get_payload(decode=True)

                if attachment_filename.lower().endswith('.pdf'):
                    resume_text = extract_text_from_pdf(attachment_content)
                elif attachment_filename.lower().endswith('.docx'):
                    resume_text = extract_text_from_docx(attachment_content)
                else:
                    continue

                # Extract details from the resume text
                details = {
                    "name": extract_name_from_text(resume_text),
                    "email": extract_email_from_text(resume_text),
                    "phone": extract_phone_from_text(resume_text),
                    "experience": extract_experience(resume_text),
                    "skills": extract_relevant_skills(resume_text, job_desc_text),
                    "certifications": extract_certifications_count(resume_text),
                    "location": extract_location_from_text(resume_text),
                    "visa_status": extract_visa_status(resume_text),
                    "government": extract_government_details(resume_text)
                }

                # Calculate the resume score
                score = calculate_resume_score(resume_text, job_desc_text, details['skills'],
                                               details['experience'], details['certifications'],
                                               details['visa_status'], details['location'])
                details['resume score'] = score
                resume_details.append(details)

    mail.logout()

    # Convert resume details to DataFrame
    df = pd.DataFrame(resume_details)
    df = df.sort_values(by='resume score', ascending=False)  # Sort by resume score in descending order
    df.insert(df.columns.get_loc('resume score') + 1, 'Rank', range(1, len(df) + 1))  # Insert Rank column beside resume score
    return df

def assign_rank(score):
    if 0 <= score <= 9:
        return 10
    elif 10 <= score <= 19:
        return 9
    elif 20 <= score <= 29:
        return 8
    elif 30 <= score <= 39:
        return 7
    elif 40 <= score <= 49:
        return 6
    elif 50 <= score <= 59:
        return 5
    elif 60 <= score <= 69:
        return 4
    elif 70 <= score <= 79:
        return 3
    elif 80 <= score <= 89:
        return 2
    elif 90 <= score <= 100:
        return 1
    return 10

import base64

# Convert image to Base64 format
def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

# Path to your logo
logo_path = r"C:/Users/shiva/Downloads/iit labs1 (2).jpeg" 
base64_logo = get_base64_image(logo_path) 

# Streamlit UI for resume shortlisting page

# Streamlit UI
st.markdown(f"""
    <style>
        body {{
            background-color: #FF0000;  /* Red background */
            margin: 0;
            padding: 0;
        }}

        @keyframes marquee {{
            0% {{
                transform: translateX(100%);  /* Start from the right edge */
            }}  

            100% {{
                transform: translateX(-100%);  /* End at the left edge */
            }}  
        }}
        .marquee-container {{
            position: absolute;
            top: 0;
            right: 0;
            width: 100%;
            height: 50px;  /* Height of the marquee container */
            overflow: hidden;
        }}

        .marquee {{
        display: flex;
        width: 100%;  /* Automatically adjust the width based on content */
        animation: marquee 10s linear infinite;  /* Continuous scrolling over 10 seconds */
        animation-timing-function: linear;  /* Constant speed */
        animation-delay: 0s;  /* No delay at the start */
    }}

        .marquee img {{
            height: 50px;  /* Adjust size */
            width: auto;
        }}

        .stButton > button {{
            background-color: black;
            color: white;
            border: none;
            padding: 10px 20px;
            text-align: center;
            font-size: 16px;
            cursor: pointer;
            border-radius: 5px;
        }}

        .stButton > button:hover {{
            background-color: black;
        }}

        .title {{
            color: #FFFF00;
            font-size: 24px;
            font-weight: bold;
            text-align: center;
        }}

        .footer {{
            position: fixed;
            bottom: 6px;
            right: 20px;
            display: flex;
            gap: 8px;
            color: black;
            font-size: 10px;
            font-weight: bold;
            padding: 10px 15px;
            border-radius: 5px;
        }}
    </style>

    <div class="marquee-container">
        <div class="marquee">
            <img src="data:image/jpeg;base64,{base64_logo}" alt="IIT Labs Logo">
        </div>
    </div>
""", unsafe_allow_html=True)


# Login Page
def login():
    st.title("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "saikumar" and password == "12345":  # Replace with your credentials
            st.session_state.logged_in = True
        else:
            st.error("Invalid username or password")

# Main Page
def main():
    st.markdown("<h1 style='text-align: center;'>Resume Shortlisting</h1>", unsafe_allow_html=True)
    job_id = st.text_input("Enter Job ID:")
    footer_placeholder = st.empty()

    if job_id:
        st.write(f"Processing resumes for Job ID: {job_id}")
        df = process_resumes_and_attachments(job_id)

        if not df.empty:
            df['Rank'] = df['resume score'].apply(assign_rank)
            df = df.sort_values(by='Rank', ascending=True)  # Sort by Rank in ascending order
            df = df.reset_index(drop=True)  # Reset index to remove the old index column
            df.index += 1  # Start index from 1
            st.write(f"Found {len(df)} resumes")
            st.dataframe(df)  # Display the dataframe in Streamlit
            footer_placeholder.markdown("""
    <div class="footer">
        <span>Copyright © 2025 IIT Labs</span>
        <span>Developed by IIT Labs</span>
    </div>
""", unsafe_allow_html=True)
        else:
            st.write("No resumes found for the specified Job ID.")

    st.button('Resume Analysing', key='blue')

# Check if user is logged in
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    login()
else:
    main()
