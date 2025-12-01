"""
Route modules for the UniversalAPI application.

This package contains all the route modules organized by functionality:
- content_routes: Core content generation routes
- image_routes: Image generation and caching routes  
- api_routes: API endpoints and admin tools
- utility_routes: Search and editing functionality

All route modules are automatically registered with the FastAPI app.
"""

from fastapi import FastAPI

from . import api_routes, content_routes, image_routes, utility_routes


def register_routes(app: FastAPI) -> None:
    """Register all route modules with the FastAPI application."""
    # Register content routes (home, random, catch-all)
    content_routes.register_routes(app)
    
    # Register image routes (PNG generation)
    image_routes.register_routes(app)
    
    # Register API routes (LLM endpoint, reset endpoints)
    api_routes.register_routes(app)
    
    # Register utility routes (search, edit)
    utility_routes.register_routes(app)