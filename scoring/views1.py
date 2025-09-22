import os
import re
import random
import tempfile
from typing import Dict
import requests
from dotenv import load_dotenv
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache

# Load API keys from .env file
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_API_KEY = os.getenv("GITHUB_API_KEY")

# ========== In-memory OTP / user stores (demo only) =========
registered_users: Dict[str, str] = {}
OTP_TTL_SECONDS = 300  # 5 min

# Helper functions to normalize inputs
def norm_email(email: str) -> str: return (email or "").strip().lower()
def norm_mobile(mobile: str) -> str: return re.sub(r"\D+", "", (mobile or "").strip())

# Send OTP email function
def send_otp_email(to_email: str, otp: str, subject: str):
    send_mail(
        subject=subject,
        message=f"Your OTP is {otp}. It will expire in {OTP_TTL_SECONDS // 60} minutes.",
        from_email=os.getenv("DEFAULT_FROM_EMAIL"),
        recipient_list=[to_email],
        fail_silently=False,
    )

# ========= Basic pages =========
def landing_page(request): 
    return render(request, "landing.html")

def signin(request): 
    return render(request, "login.html")

def login_page(request): 
    return render(request, "login.html")

def signup(request): 
    return render(request, "login.html")

def why(request): 
    return render(request, "why.html")

def who(request): 
    return render(request, "who.html")

def upload_resume(request): 
    return render(request, "upload_resume.html")

# ========= OTP SIGNUP / LOGIN =========

# Send OTP for signup
@csrf_exempt
def send_signup_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    
    email = norm_email(request.POST.get("email", ""))
    mobile = norm_mobile(request.POST.get("mobile", ""))
    
    if not email or not mobile:
        return JsonResponse({"status": "error", "message": "Email and mobile required"}, status=400)
    
    otp = f"{random.randint(100000, 999999)}"
    cache_key = f"signup_otp:{email}:{mobile}"
    cache.set(cache_key, otp, timeout=OTP_TTL_SECONDS)

    try:
        send_otp_email(email, otp, subject="Your ApplyWizz Signup OTP")
        return JsonResponse({"status": "success", "message": "OTP sent to your email"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Failed to send OTP: {e}"}, status=500)

# Verify Signup OTP
@csrf_exempt
def verify_signup_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    
    email = norm_email(request.POST.get("email", ""))
    mobile = norm_mobile(request.POST.get("mobile", ""))
    otp = (request.POST.get("otp", "") or "").strip()
    
    cache_key = f"signup_otp:{email}:{mobile}"
    stored_otp = cache.get(cache_key)
    
    if stored_otp and stored_otp == otp:
        registered_users[mobile] = email
        cache.delete(cache_key)
        return JsonResponse({"status": "success", "redirect_url": "/login"})
    else:
        return JsonResponse({"status": "error", "message": "Invalid or expired OTP"}, status=400)

# Send OTP for login
@csrf_exempt
def send_login_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    
    email = norm_email(request.POST.get("email", ""))
    
    if not email:
        return JsonResponse({"status": "error", "message": "Email required"}, status=400)
    
    otp = f"{random.randint(100000, 999999)}"
    cache_key = f"login_otp:{email}"
    cache.set(cache_key, otp, timeout=OTP_TTL_SECONDS)

    try:
        send_otp_email(email, otp, subject="Your ApplyWizz Login OTP")
        return JsonResponse({"status": "success", "message": "OTP sent to your email"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Failed to send OTP: {e}"}, status=500)

# Verify Login OTP
@csrf_exempt
def verify_login_otp(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid request"}, status=405)
    
    email = norm_email(request.POST.get("email", ""))
    otp = (request.POST.get("otp", "") or "").strip()
    
    cache_key = f"login_otp:{email}"
    stored_otp = cache.get(cache_key)
    
    if stored_otp and stored_otp == otp:
        cache.delete(cache_key)
        return JsonResponse({"status": "success", "redirect_url": "/upload_resume"})
    else:
        return JsonResponse({"status": "error", "message": "Invalid or expired OTP"}, status=400)

# Parse the resume using Gemini API
def parse_resume_with_gemini(file_path):
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}"
    }

    files = {
        'file': open(file_path, 'rb')
    }

    response = requests.post(
        "https://api.gemini.com/resume/parse",  # Gemini's resume parsing endpoint
        headers=headers,
        files=files
    )

    return response.json()

# Get GitHub data using GitHub API
def get_github_data_from_api(github_username):
    headers = {
        "Authorization": f"token {GITHUB_API_KEY}"
    }

    repos_url = f"https://api.github.com/users/{github_username}/repos"
    repos_response = requests.get(repos_url, headers=headers)
    return repos_response.json()

# Scoring calculation function
def calculate_scores(parsed_resume, job_role, github_data):
    scores = {}

    # Calculate GitHub score
    scores['github'] = calculate_github_score(github_data)

    # Calculate LinkedIn score (from parsed resume data)
    scores['linkedin'] = calculate_linkedin_score(parsed_resume)

    # Calculate Portfolio score (from parsed resume data)
    scores['portfolio'] = calculate_portfolio_score(parsed_resume)

    # Calculate Resume score (using job role)
    scores['resume'] = calculate_resume_score(parsed_resume, job_role)

    # Calculate Certifications score
    scores['certifications'] = calculate_certifications_score(parsed_resume)

    # Calculate the total score
    total_score = sum([score for score in scores.values()])
    scores['total_score'] = total_score

    return scores

# Calculate GitHub score
def calculate_github_score(github_data):
    score = 0
    if github_data:
        if len(github_data) >= 3:  # If there are 3+ repos with activity
            score = 20
        elif len(github_data) == 1:
            score = 10
        else:
            score = 5
    return score

# Calculate LinkedIn score
def calculate_linkedin_score(linkedin_data):
    score = 0
    if linkedin_data:
        if linkedin_data.get('headline'):
            score += 2
        if linkedin_data.get('about'):
            score += 3
        if linkedin_data.get('experience'):
            score += 4
        if linkedin_data.get('projects'):
            score += 3
    return score

# Calculate Resume score
def calculate_resume_score(resume_data, job_role):
    score = 0
    if resume_data:
        if job_role.lower() in resume_data.get('role', '').lower():
            score = 20
        else:
            score = 10
    return score


def calculate_certifications_score(certifications_data):
    score = 0
    # Ensure that certifications_data is a list; if it's a string or None, default to empty list
    if isinstance(certifications_data, str):
        certifications_data = []  # If it's a string, treat it as empty for this context
    elif not isinstance(certifications_data, list):
        certifications_data = []  # Default to empty list if it's neither a list nor string

    for cert in certifications_data:
        if isinstance(cert, dict) and cert.get('relevance') == 'high':  # Check if it's a dict and has 'relevance'
            score += 3  # Add points for relevant certificates

    return score


# Calculate Portfolio score (from parsed resume data)
def calculate_portfolio_score(portfolio_data):
    score = 0
    projects = portfolio_data.get('projects', 0)  # Ensure default value of 0 if not found
    if isinstance(projects, int):  # Make sure we are comparing integers
        if projects >= 3:
            score = 20
        elif projects == 1:
            score = 10
        else:
            score = 5
    return score

# The main function to process the uploaded resume and display the results
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
import os
import tempfile

@require_POST

def analyze_resume(request):
    # Check if file is uploaded
    if "resume" not in request.FILES:
        return HttpResponseBadRequest("No resume file provided.")

    resume_file = request.FILES["resume"]
    job_role = request.POST.get("job_role", "").strip()
    if not job_role:
        return HttpResponseBadRequest("Job role is required.")

    # Use a temporary file context to read the uploaded file
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(resume_file.name)[1]) as tmp:
        for chunk in resume_file.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        # ===== Parse resume via Gemini API =====
        parsed_resume_data = parse_resume_with_gemini(temp_path)

        # ===== GitHub Data =====
        github_username = parsed_resume_data.get("github")
        github_data = get_github_data_from_api(github_username) if github_username else {}

        # ===== Calculate Scores =====
        scores = calculate_scores(parsed_resume_data, job_role, github_data)

        # Extract relevant information for the template
                # Ensure data is passed correctly to template
        contact_detection = "YES" if parsed_resume_data.get("contact_detected") else "NO"
        linkedin_detection = "YES" if parsed_resume_data.get("linkedin") else "NO"
        github_detection = "YES" if parsed_resume_data.get("github") else "NO"

        # Create context for rendering
        context = {
            "applicant_name": parsed_resume_data.get("name", "Unknown"),
            "ats_score": scores.get("resume", 0),
            "overall_score_average": scores.get("total_score", 0),
            "score_breakdown": scores,
            "total_score": scores.get("total_score", 0),
            "total_grade": "Excellent" if scores.get("total_score", 0) >= 85 else ("Good" if scores.get("total_score", 0) >= 70 else "Average"),
            "profile_score_class": "score-box" if scores.get("total_score", 0) >= 85 else "score-box-orange",
            "ats_score_class": "score-box" if scores.get("resume", 0) >= 18 else "score-box-orange",
            "contact_detection": contact_detection,
            "linkedin_detection": linkedin_detection,
            "github_detection": github_detection,
            "pie_chart_image": None,  # Optional: You can generate or embed a pie chart here
            "missing_certifications": [],  # Add any missing certifications here if applicable
            "suggestions": [],  # Add suggestions for improvements
            "score_breakdown_ordered": sorted(scores.items(), key=lambda x: x[1], reverse=True)  # Sorting by score
        }

        
        return render(request, "resume_result.html", context)

    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)
