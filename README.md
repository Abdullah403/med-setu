# MED-SETU Smart India Hackathon Prototype

## Project Overview
MED-SETU is a healthcare solution developed for the Smart India Hackathon. This prototype leverages modern web technologies and machine learning to address healthcare challenges.

## Project Structure
```
med-setu/
├── app.py                 # Main application entry point
├── database/              # Database configuration and models
│   ├── __init__.py
│   ├── db.py             # Database connection and setup
│   └── models.py         # Database models (SQLAlchemy)
├── pages/                # Streamlit pages
├── services/             # Business logic and services
├── assets/               # Static assets (images, styles, etc.)
├── uploads/              # User uploaded files
├── requirements.txt      # Python dependencies
└── README.md            # This file
```

## Dependencies
- **streamlit**: Web application framework
- **sqlalchemy**: Database ORM
- **pandas**: Data manipulation and analysis
- **plotly**: Interactive visualizations
- **bcrypt**: Password hashing for security

## Getting Started
1. Install dependencies: `pip install -r requirements.txt`
2. Run the application: `streamlit run app.py`

## Development Status
🚧 Prototype Phase - Infrastructure setup complete, feature development in progress
