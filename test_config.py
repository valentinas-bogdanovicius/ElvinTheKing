#!/usr/bin/env python3
"""
Configuration Test Script

This script validates the environment configuration without executing the full workflow.
Use this to test your setup before running the main orchestrator.

Author: AI Assistant
Created: 2024
"""

import os
import sys
from pathlib import Path

# Import modules from the main script
try:
    from process_jira_ticket import ConfigManager, JiraManager, AIAgent
    import google.generativeai as genai
    from jira import JIRA
    from git import Repo
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure all dependencies are installed: pip install -r requirements.txt")
    sys.exit(1)


def test_config():
    """Test configuration loading"""
    print("Testing configuration...")
    
    try:
        config = ConfigManager()
        print("Configuration loaded successfully")
        
        # Print configuration (without sensitive data)
        print(f"   Jira Server: {config.jira_server}")
        print(f"   Jira Project: {config.jira_project_key}")
        print(f"   Git Repo: {config.git_repo_url}")
        print(f"   Workspace: {config.git_workspace_path}")
        print(f"   Gemini API Key: {'*' * (len(config.gemini_api_key) - 4) + config.gemini_api_key[-4:]}")
        
        return config
    except Exception as e:
        print(f"Configuration error: {e}")
        return None


def test_jira_connection(config):
    """Test Jira API connection"""
    print("\nTesting Jira connection...")
    
    try:
        # Simple connection test with shorter timeout
        from jira import JIRA
        
        # Create JIRA connection with timeout
        jira_client = JIRA(
            server=config.jira_server,
            basic_auth=(config.jira_username, config.jira_api_token),
            options={'server': config.jira_server, 'timeout': 15}
        )
        
        # Test basic connection by getting server info
        server_info = jira_client.server_info()
        print(f"Connected to Jira server: {server_info.get('serverTitle', 'Unknown')}")
        
        # Test project access (simplified)
        try:
            project = jira_client.project(config.jira_project_key)
            print(f"Project access confirmed: {project.name}")
        except Exception as project_error:
            print(f"Project access warning: {project_error}")
            print("(This may be due to permissions, but basic connection works)")
        
        return True
        
    except Exception as e:
        print(f"Jira connection error: {e}")
        print("Please verify your Jira credentials and server URL")
        return False


def test_gemini_connection(config):
    """Test Gemini AI API connection"""
    print("\nTesting Gemini AI connection...")
    
    try:
        import google.generativeai as genai
        
        # Configure with timeout
        genai.configure(api_key=config.gemini_api_key)
        
        # Test with a simple model creation first
        model = genai.GenerativeModel(config.gemini_model)
        print("Gemini AI model initialized successfully")
        
        # Test with a simple prompt (with manual timeout handling)
        print("Testing AI response generation...")
        test_prompt = "Reply with exactly: 'Connection test successful'"
        
        try:
            response = model.generate_content(test_prompt)
            
            if response and response.text:
                print(f"Gemini AI connected successfully")
                print(f"   Response: {response.text.strip()}")
                return True
            else:
                print("Gemini AI connection failed: No response received")
                return False
        except Exception as response_error:
            print(f"Gemini AI response error: {response_error}")
            print("Note: Model initialized successfully, but response generation failed")
            print("This could be due to API quotas or network issues")
            return False
            
    except Exception as e:
        print(f"Gemini AI connection error: {e}")
        print("Please verify your Gemini API key")
        return False


def test_git_access(config):
    """Test Git repository access"""
    print("\nTesting Git repository access...")
    
    try:
        # Test if workspace path is accessible
        workspace_path = Path(config.git_workspace_path)
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"Workspace path accessible: {workspace_path}")
        
        # Note: We don't actually clone here to avoid modifying the workspace
        # Just validate the URL format
        repo_url = config.git_repo_url
        if repo_url.startswith(('https://', 'ssh://', 'git@')):
            print(f"Git repository URL format valid: {repo_url}")
            return True
        else:
            print(f"Invalid Git repository URL format: {repo_url}")
            return False
            
    except Exception as e:
        print(f"Git access error: {e}")
        return False


def main():
    """Main test function"""
    print("AI-Driven Development Workflow - Configuration Test")
    print("=" * 60)
    
    # Test configuration
    config = test_config()
    if not config:
        print("\nConfiguration test failed. Please check your .env file.")
        sys.exit(1)
    
    # Run connection tests
    tests = [
        ("Jira", test_jira_connection, config),
        ("Gemini AI", test_gemini_connection, config),
        ("Git", test_git_access, config)
    ]
    
    results = {}
    for test_name, test_func, config_obj in tests:
        results[test_name] = test_func(config_obj)
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary:")
    
    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"   {test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\nAll tests passed! Your configuration is ready.")
        print("You can now run: python process_jira_ticket.py")
    else:
        print("\nSome tests failed. Please check the errors above.")
        print("Ensure all credentials are correct and services are accessible.")
    
    print("\nNote: This test doesn't actually clone the Git repository")
    print("   or process any Jira tickets. It only validates connectivity.")


if __name__ == "__main__":
    main() 