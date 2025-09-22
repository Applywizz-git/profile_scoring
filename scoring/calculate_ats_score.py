import os
import re
import fitz  # PyMuPDF
import docx2txt
import requests
from dotenv import load_dotenv

load_dotenv()

# --- Resume Text Extraction ---
def extract_text_from_pdf(file_path):
    """Extracts text from a PDF file using PyMuPDF (fitz)."""
    text = ""
    try:
        doc = fitz.open(file_path)
        for page in doc:
            text += page.get_text()
    except Exception:
        pass
    return text

def extract_text_from_docx(file_path):
    """Extracts text from a DOCX file using docx2txt."""
    try:
        return docx2txt.process(file_path)
    except Exception:
        return ""

# --- Link Extractors ---
def extract_link(pattern, text):
    """Extracts a single link from text based on a regex pattern."""
    match = re.search(pattern, text)
    return match.group(0) if match else None

# --- Scoring Functions ---
def score_github(github_json):
    """Scores GitHub presence based on the number of repos, commits, and quality."""
    if github_json:
        repo_count = len(github_json.get('repos', []))
        significant_contribs = sum(1 for repo in github_json['repos'] if repo.get('commits', 0) > 5 and repo.get('readme') and repo.get('tests'))
        if repo_count >= 3 and significant_contribs >= 2:
            return 27
        elif repo_count == 1 and significant_contribs > 0:
            return 18
        elif repo_count >= 1:
            return 10
        else:
            return 2
    return 0

def score_leetcode(leetcode_url):
    """Placeholder for LeetCode scoring."""
    return 20 if leetcode_url else 0

def score_portfolio(portfolio_extract):
    """Scores Portfolio based on the number of projects and case studies."""
    if portfolio_extract and 'projects' in portfolio_extract:
        project_count = len(portfolio_extract['projects'])
        case_studies = sum(1 for project in portfolio_extract['projects'] if project.get('case_study'))
        if project_count >= 3 and case_studies >= 2:
            return 23
        elif project_count >= 2:
            return 15
        elif project_count == 1:
            return 9
        else:
            return 3
    return 0

def score_linkedin(linkedin_json, resume_text):
    """Scores LinkedIn based on various sections."""
    linkedin_score = 0
    
    # Headline
    headline_score = 2 if 'role' in linkedin_json.get('headline', '').lower() else 0
    linkedin_score += headline_score
    
    # About
    about_score = 3 if 'achievements' in linkedin_json.get('about', '').lower() else 0
    linkedin_score += about_score
    
    # Experience
    experience_score = sum(1 for exp in linkedin_json.get('experience', []) if 'quantified' in exp.get('description', '').lower())
    linkedin_score += min(experience_score, 4)
    
    # Projects
    projects_score = sum(1 for proj in linkedin_json.get('projects', []) if proj.get('links'))
    linkedin_score += min(projects_score, 3)
    
    # Education
    education_score = 2 if 'degree' in linkedin_json.get('education', '') else 0
    linkedin_score += education_score
    
    # Skills
    skills_score = 2 if len(linkedin_json.get('skills', [])) > 5 else 0
    linkedin_score += skills_score
    
    # Certifications
    certifications_score = 2 if 'certificate' in linkedin_json.get('certifications', '') else 0
    linkedin_score += certifications_score
    
    return linkedin_score

def score_resume_structure(resume_text):
    """Scores Resume based on ATS-friendliness and structure."""
    if resume_text:
        if 'quantifiable' in resume_text.lower():
            return 20
        elif 'skills' in resume_text.lower():
            return 15
        elif 'experience' in resume_text.lower():
            return 10
    return 0

def score_certifications(certifications):
    """Scores certifications based on relevance and applied learning."""
    relevant_certificates = sum(1 for cert in certifications if cert.get('relevance_tag') == 'relevant')
    applied_certificates = sum(1 for cert in certifications if cert.get('applied'))
    if relevant_certificates >= 2:
        return 9
    elif relevant_certificates == 1:
        return 5
    else:
        return 1

# --- Main Logic ---
def get_overall_score(file_path, github_json, linkedin_json, portfolio_extract, certifications):
    """
    Calculates an overall ATS score based on file content.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        text = extract_text_from_pdf(file_path)
    elif ext == '.docx':
        text = extract_text_from_docx(file_path)
    else:
        return {"error": "Unsupported file format."}

    github_url = extract_link(r'https?://github\.com/[A-Za-z0-9_-]+', text)
    linkedin_url = extract_link(r'https?://(www\.)?linkedin\.com/in/[A-Za-z0-9_-]+', text)
    portfolio_url = extract_link(r'https?://[a-zA-Z0-9.-]+\.(me|tech|dev|xyz|site|vercel\.app|github\.io)', text)

    scores = {
        "GitHub": score_github(github_json),
        "LeetCode": score_leetcode(linkedin_url),
        "Portfolio": score_portfolio(portfolio_extract),
        "LinkedIn": score_linkedin(linkedin_json, text),
        "Resume": score_resume_structure(text),
        "Certifications": score_certifications(certifications)
    }

    total = sum(scores.values())
    final_score = min(total, 100)

    return {
        "scores": scores,
        "total": final_score
    }
