#!/usr/bin/env python3
"""
Enhanced Orchestrator Script for AI-Driven Development Workflow

This script automates the process of:
1. Fetching Jira tickets and checking for branch requirements
2. Preparing workspace with main/specified branch
3. Creating feature branch and immediately updating Jira
4. Generating specifications via BA Agent with full codebase context
5. Implementing code changes via Coding Agent with comprehensive context
6. Committing changes to Git and updating Jira status
7. Launching application locally for testing

Author: AI Assistant
Enhanced: 2024
"""

import os
import sys
import json
import logging
import shutil
import tempfile
import re
import threading
import time
import socket
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from http.server import HTTPServer, SimpleHTTPRequestHandler
import base64
import requests

# Third-party imports
import google.generativeai as genai
from jira import JIRA
from git import Repo, InvalidGitRepositoryError
from dotenv import load_dotenv
import patch
import requests # Added for the new BA agent method


@dataclass
class JiraTicket:
    """Data class to hold Jira ticket information"""
    key: str
    summary: str
    description: str
    comments: List[str]
    specified_branch: Optional[str] = None


class ConfigManager:
    """Manages configuration loading from environment variables"""
    
    def __init__(self):
        load_dotenv()
        self.validate_config()
    
    def validate_config(self):
        """Validate that all required environment variables are present"""
        required_vars = [
            'JIRA_SERVER', 'JIRA_USERNAME', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY',
            'GEMINI_API_KEY', 'GIT_REPO_URL', 'GIT_WORKSPACE_PATH'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    @property
    def jira_server(self) -> str:
        return os.getenv('JIRA_SERVER')
    
    @property
    def jira_username(self) -> str:
        return os.getenv('JIRA_USERNAME')
    
    @property
    def jira_api_token(self) -> str:
        return os.getenv('JIRA_API_TOKEN')
    
    @property
    def jira_project_key(self) -> str:
        return os.getenv('JIRA_PROJECT_KEY')
    
    @property
    def gemini_api_key(self) -> str:
        return os.getenv('GEMINI_API_KEY')
    
    @property
    def git_repo_url(self) -> str:
        return os.getenv('GIT_REPO_URL')
    
    @property
    def git_workspace_path(self) -> str:
        return os.getenv('GIT_WORKSPACE_PATH', './workspace')
    
    @property
    def gemini_model(self) -> str:
        return os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-exp')


class JiraManager:
    """Handles all Jira-related operations"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.jira = JIRA(
            server=config.jira_server,
            basic_auth=(config.jira_username, config.jira_api_token)
        )
        self.logger = logging.getLogger(__name__)
    
    def download_ticket_attachments(self, ticket_key: str, attachments_path: Path) -> Dict[str, str]:
        """Download all attachments from a Jira ticket and return attachment info"""
        try:
            issue = self.jira.issue(ticket_key, expand='attachment')
            attachments_info = {}
            
            if not hasattr(issue.fields, 'attachment') or not issue.fields.attachment:
                self.logger.info(f"No attachments found for ticket {ticket_key}")
                return attachments_info
            
            self.logger.info(f"Found {len(issue.fields.attachment)} attachment(s) for ticket {ticket_key}")
            
            for attachment in issue.fields.attachment:
                try:
                    # Get attachment content
                    attachment_content = attachment.get()
                    
                    # Create safe filename
                    safe_filename = "".join(c for c in attachment.filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
                    if not safe_filename:
                        safe_filename = f"attachment_{attachment.id}"
                    
                    # Save to attachments directory
                    file_path = attachments_path / safe_filename
                    
                    # Handle potential filename conflicts
                    counter = 1
                    original_path = file_path
                    while file_path.exists():
                        name_parts = original_path.stem, counter, original_path.suffix
                        file_path = original_path.parent / f"{name_parts[0]}_{name_parts[1]}{name_parts[2]}"
                        counter += 1
                    
                    with open(file_path, 'wb') as f:
                        f.write(attachment_content)
                    
                    # Store attachment info
                    attachments_info[str(file_path.name)] = {
                        'original_filename': attachment.filename,
                        'size': attachment.size,
                        'mimetype': getattr(attachment, 'mimeType', 'unknown'),
                        'created': str(attachment.created),
                        'author': str(attachment.author),
                        'local_path': str(file_path)
                    }
                    
                    self.logger.info(f"Downloaded attachment: {attachment.filename} -> {file_path.name}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to download attachment {attachment.filename}: {e}")
                    continue
            
            return attachments_info
            
        except Exception as e:
            self.logger.error(f"Failed to download attachments for ticket {ticket_key}: {e}")
            return {}
    
    def get_oldest_open_ticket(self) -> Optional[JiraTicket]:
        """Fetch the oldest open/reopened ticket from the specified project"""
        try:
            jql = f'project = {self.config.jira_project_key} AND status IN ("Open", "Reopened") ORDER BY created ASC'
            issues = self.jira.search_issues(jql, maxResults=1)
            
            if not issues:
                self.logger.info("No open tickets found")
                return None
            
            issue = issues[0]
            
            # Get all comments
            comments = []
            if hasattr(issue.fields, 'comment') and issue.fields.comment.comments:
                comments = [comment.body for comment in issue.fields.comment.comments]
            
            # Extract specified branch from description/comments if any
            specified_branch = self._extract_branch_from_ticket(
                issue.fields.description or "", comments
            )
            
            return JiraTicket(
                key=issue.key,
                summary=issue.fields.summary,
                description=issue.fields.description or "",
                comments=comments,
                specified_branch=specified_branch
            )
            
        except Exception as e:
            self.logger.error(f"Failed to fetch Jira ticket: {e}")
            raise
    
    def _extract_branch_from_ticket(self, description: str, comments: List[str]) -> Optional[str]:
        """Extract branch name from ticket description or comments"""
        # Look for patterns like "branch: feature/xyz" or "use branch feature/xyz"
        branch_patterns = [
            r'branch[:\s]+([a-zA-Z0-9/_-]+)',
            r'use\s+branch[:\s]+([a-zA-Z0-9/_-]+)',
            r'from\s+branch[:\s]+([a-zA-Z0-9/_-]+)',
            r'checkout\s+([a-zA-Z0-9/_-]+)',
        ]
        
        all_text = description + " " + " ".join(comments)
        
        for pattern in branch_patterns:
            match = re.search(pattern, all_text, re.IGNORECASE)
            if match:
                branch_name = match.group(1)
                # Validate branch name format
                if re.match(r'^[a-zA-Z0-9/_-]+$', branch_name):
                    return branch_name
        
        return None
    
    def add_comment(self, ticket_key: str, comment: str):
        """Add a comment to the specified Jira ticket"""
        try:
            self.jira.add_comment(ticket_key, comment)
            self.logger.info(f"Added comment to ticket {ticket_key}")
        except Exception as e:
            self.logger.error(f"Failed to add comment to ticket {ticket_key}: {e}")
            raise
    
    def transition_ticket(self, ticket_key: str, status: str):
        """Transition ticket to the specified status using Jira REST API"""
        try:
            # First, get available transitions for the issue
            transitions_url = f"{self.config.jira_server}/rest/api/3/issue/{ticket_key}/transitions"
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Basic {base64.b64encode(f"{self.config.jira_username}:{self.config.jira_api_token}".encode()).decode()}'
            }
            
            response = requests.get(transitions_url, headers=headers)
            response.raise_for_status()
            
            transitions_data = response.json()
            transition_id = None
            
            # Find the transition that matches the target status
            for transition in transitions_data.get('transitions', []):
                if transition.get('to', {}).get('name', '').lower() == status.lower():
                    transition_id = transition.get('id')
                    break
            
            if not transition_id:
                # Log available transitions for debugging
                available_transitions = [t.get('to', {}).get('name', 'Unknown') for t in transitions_data.get('transitions', [])]
                self.logger.warning(f"Status '{status}' not available for ticket {ticket_key}. Available transitions: {available_transitions}")
                return
            
            # Perform the transition
            transition_url = f"{self.config.jira_server}/rest/api/3/issue/{ticket_key}/transitions"
            transition_data = {
                "transition": {
                    "id": transition_id
                }
            }
            
            response = requests.post(transition_url, headers=headers, json=transition_data)
            response.raise_for_status()
            
            self.logger.info(f"Successfully transitioned ticket {ticket_key} to {status}")
                
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to transition ticket {ticket_key} to {status}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                self.logger.error(f"Response status: {e.response.status_code}")
                self.logger.error(f"Response body: {e.response.text}")
        except Exception as e:
            self.logger.error(f"Failed to transition ticket {ticket_key} to {status}: {e}")
            raise


class GitManager:
    """Handles all Git-related operations"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.workspace_path = Path(config.git_workspace_path)
        self.repo = None
        self.logger = logging.getLogger(__name__)
    
    def prepare_workspace(self, specified_branch: Optional[str] = None):
        """Clone or prepare the Git workspace with specified or main branch"""
        try:
            if self.workspace_path.exists():
                # Try to open existing repo
                try:
                    self.repo = Repo(str(self.workspace_path))
                    self.logger.info("Found existing repository")
                    
                    # Clean workspace
                    self.repo.git.reset('--hard')
                    self.repo.git.clean('-fdx')
                    
                    # Try to checkout specified branch or main
                    if specified_branch:
                        try:
                            # First try to fetch updates
                            self.repo.git.fetch()
                            
                            # Check if branch exists locally
                            local_branches = [ref.name.split('/')[-1] for ref in self.repo.refs if ref.name.startswith('refs/heads/')]
                            remote_branches = [ref.name.split('/')[-1] for ref in self.repo.refs if ref.name.startswith('refs/remotes/origin/')]
                            
                            if specified_branch in local_branches:
                                # Branch exists locally
                                self.repo.git.checkout(specified_branch)
                                if specified_branch in remote_branches:
                                    self.repo.git.pull('origin', specified_branch)
                                self.logger.info(f"Checked out existing local branch: {specified_branch}")
                            elif specified_branch in remote_branches:
                                # Branch exists on remote but not locally
                                self.repo.git.checkout('-b', specified_branch, f'origin/{specified_branch}')
                                self.logger.info(f"Checked out remote branch: {specified_branch}")
                            else:
                                # Branch doesn't exist, fallback to main
                                self.logger.info(f"Branch {specified_branch} doesn't exist, falling back to main")
                                self.repo.git.checkout('main')
                                self.repo.git.pull()
                        except Exception as e:
                            self.logger.warning(f"Failed to checkout {specified_branch}, falling back to main: {e}")
                            try:
                                self.repo.git.checkout('main')
                                self.repo.git.pull()
                            except Exception as e2:
                                self.logger.warning(f"Failed to checkout main, trying master: {e2}")
                                self.repo.git.checkout('master')
                                self.repo.git.pull()
                    else:
                        # No specific branch requested, use main
                        try:
                            self.repo.git.checkout('main')
                            self.repo.git.pull()
                            self.logger.info("Checked out and updated main branch")
                        except Exception as e:
                            self.logger.warning(f"Failed to checkout main, trying master: {e}")
                            self.repo.git.checkout('master')
                            self.repo.git.pull()
                            self.logger.info("Checked out and updated master branch")
                    
                except InvalidGitRepositoryError:
                    self.logger.info("Invalid repository found, removing and cloning fresh")
                    shutil.rmtree(self.workspace_path)
                    self._clone_repository(specified_branch)
            else:
                self._clone_repository(specified_branch)
                
        except Exception as e:
            self.logger.error(f"Failed to prepare workspace: {e}")
            raise
    
    def _clone_repository(self, specified_branch: Optional[str] = None):
        """Clone the repository to workspace"""
        try:
            self.workspace_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Always clone main/master first to ensure we have a working base
            try:
                # Try main first
                self.repo = Repo.clone_from(self.config.git_repo_url, str(self.workspace_path))
                self.logger.info(f"Cloned repository (main branch) to {self.workspace_path}")
            except Exception as e:
                # Try master as fallback
                try:
                    self.repo = Repo.clone_from(
                        self.config.git_repo_url, 
                        str(self.workspace_path),
                        branch='master'
                    )
                    self.logger.info(f"Cloned repository (master branch) to {self.workspace_path}")
                except Exception as e2:
                    self.logger.error(f"Failed to clone from both main and master: {e}, {e2}")
                    raise
            
            # If a specific branch was requested, try to switch to it
            if specified_branch and specified_branch not in ['main', 'master']:
                try:
                    # First fetch all remote branches
                    self.repo.git.fetch()
                    
                    # Check if branch exists on remote using reliable Git command
                    try:
                        # Use git ls-remote to check if branch exists on remote
                        result = self.repo.git.ls_remote('--heads', 'origin', specified_branch)
                        branch_exists_on_remote = bool(result.strip())
                    except:
                        # Fallback to checking local remote refs
                        remote_branches = [ref.name.split('/')[-1] for ref in self.repo.refs if ref.name.startswith('refs/remotes/origin/')]
                        branch_exists_on_remote = specified_branch in remote_branches
                    
                    if branch_exists_on_remote:
                        # Branch exists on remote, check it out
                        self.logger.info(f"Branch {specified_branch} exists on remote, checking it out")
                        try:
                            # Try to check out as new branch from remote
                            self.repo.git.checkout('-b', specified_branch, f'origin/{specified_branch}')
                        except Exception as checkout_error:
                            # If it fails because branch already exists locally, just switch to it
                            if "already exists" in str(checkout_error):
                                self.logger.info(f"Branch {specified_branch} already exists locally, switching to it")
                                self.repo.git.checkout(specified_branch)
                                # Pull latest changes to ensure it's up to date
                                try:
                                    self.repo.git.pull('origin', specified_branch)
                                    self.logger.info(f"Pulled latest changes for existing branch {specified_branch}")
                                except Exception as pull_error:
                                    self.logger.warning(f"Could not pull from remote branch {specified_branch}: {pull_error}")
                            else:
                                raise checkout_error
                    else:
                        self.logger.info(f"Branch {specified_branch} doesn't exist on remote, will create it later")
                        # We'll stay on main/master for now, and create the branch in create_feature_branch
                        
                except Exception as e:
                    self.logger.warning(f"Failed to switch to branch {specified_branch}: {e}")
                    self.logger.info("Continuing with main/master branch")
                
        except Exception as e:
            self.logger.error(f"Failed to clone repository: {e}")
            raise
    
    def create_feature_branch(self, branch_name: str) -> str:
        """Create a new feature branch or switch to existing one, and return the full branch name"""
        try:
            # Check if we're already on the target branch
            current_branch = self.repo.active_branch.name
            if current_branch == branch_name:
                self.logger.info(f"Already on target branch {branch_name}")
                return branch_name
            
            # Check if the branch already exists locally
            existing_branches = [ref.name.split('/')[-1] for ref in self.repo.refs if ref.name.startswith('refs/heads/')]
            
            if branch_name in existing_branches:
                # Branch exists locally, switch to it
                self.logger.info(f"Branch {branch_name} already exists locally, switching to it")
                self.repo.git.checkout(branch_name)
                # Pull latest changes from remote if the branch exists there too
                try:
                    self.repo.git.pull('origin', branch_name)
                    self.logger.info(f"Pulled latest changes for existing branch {branch_name}")
                except Exception as e:
                    self.logger.warning(f"Could not pull from remote branch {branch_name}: {e}")
            else:
                # Check if branch exists on remote
                try:
                    # Fetch latest remote info
                    self.repo.git.fetch()
                    
                    # Check if branch exists on remote using reliable Git command
                    try:
                        # Use git ls-remote to check if branch exists on remote
                        result = self.repo.git.ls_remote('--heads', 'origin', branch_name)
                        branch_exists_on_remote = bool(result.strip())
                    except:
                        # Fallback to checking local remote refs
                        remote_branches = [ref.name.split('/')[-1] for ref in self.repo.refs if ref.name.startswith('refs/remotes/origin/')]
                        branch_exists_on_remote = branch_name in remote_branches
                    
                    if branch_exists_on_remote:
                        # Branch exists on remote, check it out
                        self.logger.info(f"Branch {branch_name} exists on remote, checking it out")
                        try:
                            # Try to check out as new branch from remote
                            self.repo.git.checkout('-b', branch_name, f'origin/{branch_name}')
                        except Exception as checkout_error:
                            # If it fails because branch already exists locally, just switch to it
                            if "already exists" in str(checkout_error):
                                self.logger.info(f"Branch {branch_name} already exists locally, switching to it")
                                self.repo.git.checkout(branch_name)
                                # Pull latest changes to ensure it's up to date
                                try:
                                    self.repo.git.pull('origin', branch_name)
                                    self.logger.info(f"Pulled latest changes for existing branch {branch_name}")
                                except Exception as pull_error:
                                    self.logger.warning(f"Could not pull from remote branch {branch_name}: {pull_error}")
                            else:
                                raise checkout_error
                    else:
                        # Branch doesn't exist anywhere, create new one
                        self.logger.info(f"Creating new branch {branch_name}")
                        # Ensure we're on the correct base branch first
                        if current_branch != 'main':
                            try:
                                self.repo.git.checkout('main')
                                self.repo.git.pull()
                            except:
                                pass  # Continue if we can't switch to main
                        self.repo.git.checkout('-b', branch_name)
                        
                except Exception as e:
                    self.logger.warning(f"Error checking remote branches: {e}")
                    # Fallback: try to create the branch anyway
                    self.repo.git.checkout('-b', branch_name)
            
            self.logger.info(f"Successfully working on branch {branch_name}")
            return branch_name
            
        except Exception as e:
            self.logger.error(f"Failed to create/switch to branch {branch_name}: {e}")
            raise
    
    def get_codebase_structure(self) -> str:
        """Get a formatted string representation of the codebase structure"""
        structure_lines = []
        
        # Define directories/files to exclude
        exclude_patterns = {
            '.git', '__pycache__', '.pytest_cache', 'node_modules', 
            '.vscode', '.idea', 'venv', 'env', '.env'
        }
        
        try:
            # Get all files and directories
            all_items = list(self.workspace_path.rglob('*'))
            
            # Sort items for consistent output
            all_items.sort(key=lambda x: str(x))
            
            for item_path in all_items:
                # Skip if in excluded patterns
                if any(pattern in str(item_path) for pattern in exclude_patterns):
                    continue
                
                # Calculate relative path and depth
                relative_path = item_path.relative_to(self.workspace_path)
                depth = len(relative_path.parts)
                
                # Create indentation based on depth
                indent = "  " * (depth - 1) if depth > 1 else ""
                
                # Add appropriate symbol
                if item_path.is_dir():
                    structure_lines.append(f"{indent}📁 {relative_path.name}/")
                else:
                    structure_lines.append(f"{indent}📄 {relative_path.name}")
            
            if structure_lines:
                return "Project Structure:\n" + "\n".join(structure_lines)
            else:
                return "Project Structure: No files found"
                
        except Exception as e:
            self.logger.error(f"Failed to get codebase structure: {e}")
            return "Project Structure: Error reading structure"
    
    def get_all_file_contents(self) -> Dict[str, str]:
        """Read all text files in the workspace and return as dict"""
        file_contents = {}
        
        # Define text file extensions to include
        text_extensions = {
            '.py', '.js', '.html', '.htm', '.css', '.json', '.md', '.txt', 
            '.yml', '.yaml', '.xml', '.sql', '.sh', '.bat', '.env'
        }
        
        # Define directories/files to exclude
        exclude_patterns = {
            '.git', '__pycache__', '.pytest_cache', 'node_modules', 
            '.vscode', '.idea', 'venv', 'env', '.env'
        }
        
        try:
            for file_path in self.workspace_path.rglob('*'):
                # Skip if it's a directory
                if file_path.is_dir():
                    continue
                
                # Skip if in excluded patterns
                if any(pattern in str(file_path) for pattern in exclude_patterns):
                    continue
                
                # Skip if not a text file
                if file_path.suffix.lower() not in text_extensions:
                    continue
                
                # Skip if file is too large (>1MB)
                if file_path.stat().st_size > 1024 * 1024:
                    continue
                
                try:
                    relative_path = file_path.relative_to(self.workspace_path)
                    with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        file_contents[str(relative_path)] = f.read()
                except Exception as e:
                    self.logger.warning(f"Failed to read file {file_path}: {e}")
                    continue
            
            self.logger.info(f"Read {len(file_contents)} files from workspace")
            return file_contents
            
        except Exception as e:
            self.logger.error(f"Failed to read workspace files: {e}")
            return {}
    
    def create_file(self, file_path: str, content: str) -> bool:
        """Create a new file with the specified content"""
        try:
            target_path = self.workspace_path / file_path
            
            # Check if file already exists
            if target_path.exists():
                self.logger.warning(f"File already exists, will overwrite: {file_path}")
            
            # Create directory if it doesn't exist
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the content
            with open(target_path, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            
            self.logger.info(f"Successfully created file: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating file {file_path}: {e}")
            return False

    def copy_file(self, source_path: str, target_path: str, attachments_path: Path) -> bool:
        """Copy a file from attachments directory to the workspace"""
        try:
            # Handle both relative paths and full paths with attachments/ prefix
            if source_path.startswith('attachments/'):
                # Remove the attachments/ prefix since we're already working with attachments_path
                relative_source = source_path[12:]  # Remove 'attachments/' prefix
                source_file = attachments_path / relative_source
            else:
                # Assume it's already a relative path within attachments
                source_file = attachments_path / source_path
            
            target_file = self.workspace_path / target_path
            
            # Check if source file exists
            if not source_file.exists():
                self.logger.error(f"Source file does not exist: {source_path} (looked for {source_file})")
                return False
            
            # Create target directory if it doesn't exist
            target_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy the file
            shutil.copy2(source_file, target_file)
            
            self.logger.info(f"Successfully copied file: {source_path} -> {target_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error copying file {source_path} to {target_path}: {e}")
            return False

    def delete_file(self, file_path: str) -> bool:
        """Delete a file from the workspace"""
        try:
            target_path = self.workspace_path / file_path
            
            # Check if file exists
            if not target_path.exists():
                self.logger.warning(f"File does not exist, skipping deletion: {file_path}")
                return True  # Consider this a success since the end result is achieved
            
            # Delete the file
            target_path.unlink()
            
            self.logger.info(f"Successfully deleted file: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting file {file_path}: {e}")
            return False

    def write_file_content(self, file_path: str, content: str) -> bool:
        """Write complete file content to the specified path"""
        try:
            target_path = self.workspace_path / file_path
            
            # Create directory if it doesn't exist
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the content
            with open(target_path, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            
            self.logger.info(f"Successfully wrote file: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error writing file {file_path}: {e}")
            return False
    
    def get_file_content(self, file_path: str) -> Optional[str]:
        """Get the content of a specific file in the workspace"""
        try:
            target_path = self.workspace_path / file_path
            
            if not target_path.exists():
                self.logger.warning(f"File does not exist: {file_path}")
                return None
            
            # Skip if file is too large (>1MB)
            if target_path.stat().st_size > 1024 * 1024:
                self.logger.warning(f"File too large to read: {file_path}")
                return f"[FILE TOO LARGE - {target_path.stat().st_size} bytes]"
            
            with open(target_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()
            
            self.logger.info(f"Successfully read file: {file_path}")
            return content
            
        except Exception as e:
            self.logger.error(f"Error reading file {file_path}: {e}")
            return None
    
    def replace_file_lines(self, file_path: str, start_line: int, end_line: int, new_content: str) -> Tuple[bool, Optional[str]]:
        """Replace specific lines in a file with new content. Returns (success, updated_file_content)"""
        try:
            target_path = self.workspace_path / file_path
            
            # Read current file content
            if not target_path.exists():
                self.logger.warning(f"File does not exist: {file_path}")
                return False, None
            
            with open(target_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                lines = f.readlines()
            
            # Log current file state for debugging
            self.logger.info(f"File {file_path} has {len(lines)} lines. Replacing lines {start_line}-{end_line}")
            
            # Validate line numbers (1-indexed)
            if start_line < 1 or end_line < 1 or start_line > len(lines) + 1 or end_line > len(lines):
                self.logger.error(f"Invalid line numbers: {start_line}-{end_line} for file with {len(lines)} lines")
                return False, None
            
            # Validate start_line <= end_line
            if start_line > end_line:
                self.logger.error(f"Invalid range: start_line ({start_line}) > end_line ({end_line})")
                return False, None
            
            # Prevent massive replacements that suggest the agent is confused
            lines_to_replace = end_line - start_line + 1
            if lines_to_replace > len(lines) * 0.8:  # More than 80% of the file
                self.logger.error(f"Refusing to replace {lines_to_replace} lines ({lines_to_replace/len(lines)*100:.1f}% of file) - this suggests the agent should use create_file instead")
                return False, None
            
            # Log what content is being replaced for debugging
            self.logger.info(f"Replacing content from line {start_line} to {end_line}:")
            for i in range(start_line - 1, min(end_line, len(lines))):
                self.logger.info(f"  Line {i+1}: {lines[i].rstrip()}")
            
            # Convert to 0-indexed for list operations
            start_idx = start_line - 1
            end_idx = end_line - 1
            
            # Prepare new content - ensure it ends with newline if file is not empty
            new_lines = []
            if new_content:
                # Split new content into lines, preserving any existing newlines
                new_lines = new_content.splitlines(keepends=True)
                # Ensure proper newline handling
                if new_lines:
                    # If the last line doesn't end with newline, add one
                    if not new_lines[-1].endswith('\n'):
                        new_lines[-1] += '\n'
                else:
                    # If new_content is empty, create an empty line
                    new_lines = ['\n']
            
            # Log new content being inserted
            self.logger.info(f"Inserting {len(new_lines)} new lines:")
            for i, line in enumerate(new_lines):
                self.logger.info(f"  New line {i+1}: {line.rstrip()}")
            
            # Perform the replacement
            updated_lines = lines[:start_idx] + new_lines + lines[end_idx + 1:]
            
            # Basic HTML structure validation for HTML files
            if file_path.endswith(('.htm', '.html')):
                updated_content_str = ''.join(updated_lines)
                # Check for basic HTML structure issues
                if '<head>' in updated_content_str and '</head>' not in updated_content_str:
                    self.logger.warning(f"HTML validation warning: Missing </head> tag after replacement in {file_path}")
                if '<body>' in updated_content_str and '</body>' not in updated_content_str:
                    self.logger.warning(f"HTML validation warning: Missing </body> tag after replacement in {file_path}")
                if updated_content_str.count('<div') != updated_content_str.count('</div>'):
                    self.logger.warning(f"HTML validation warning: Unmatched div tags after replacement in {file_path}")
                
                # Check for orphaned closing tags (critical structural errors)
                orphaned_tags = []
                if '</header>' in updated_content_str and '<header' not in updated_content_str:
                    orphaned_tags.append('</header>')
                if '</nav>' in updated_content_str and '<nav' not in updated_content_str:
                    orphaned_tags.append('</nav>')
                if '</section>' in updated_content_str and '<section' not in updated_content_str:
                    orphaned_tags.append('</section>')
                
                if orphaned_tags:
                    self.logger.error(f"HTML validation ERROR: Orphaned closing tags found in {file_path}: {orphaned_tags}")
                    return False, f"HTML validation failed: Orphaned closing tags found: {orphaned_tags}. This would create invalid HTML structure."
            
            # Write back to file
            with open(target_path, 'w', encoding='utf-8', newline='') as f:
                f.writelines(updated_lines)
            
            # Return success and the updated content
            updated_content = ''.join(updated_lines)
            self.logger.info(f"Successfully replaced lines {start_line}-{end_line} in file: {file_path}. New file has {len(updated_lines)} lines")
            return True, updated_content
            
        except Exception as e:
            self.logger.error(f"Error replacing lines in file {file_path}: {e}")
            return False, None
    
    def apply_patch_to_file(self, file_path: str, patch_content: str) -> bool:
        """Apply a unified diff patch to a file with a robust method. Returns True if successful."""
        full_file_path = self.workspace_path / file_path

        if not full_file_path.exists():
            self.logger.info(f"File {file_path} does not exist, creating it.")
            full_file_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(full_file_path, 'w', encoding='utf-8') as f:
                    f.write("") 
            except Exception as e:
                self.logger.error(f"Failed to create file {file_path}: {e}")
                return False
        
        original_content = ""
        try:
            # Step 1: Read original content and normalize its line endings in memory
            with open(full_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_content = f.read()
            
            normalized_original_content = original_content.replace('\r\n', '\n')
            
            # Step 2: Normalize patch content line endings
            patch_content = patch_content.replace('\r\n', '\n')

            # Step 3: Use patch.fromstring and apply relative to the workspace root
            patch_set = patch.fromstring(patch_content.encode('utf-8'))
            
            # This is the key: `root=self.workspace_path` tells the patch tool where to find `a/footer.htm`, etc.
            if patch_set.apply(root=self.workspace_path):
                self.logger.info(f"Successfully applied patch to {file_path}")
                return True
            else:
                self.logger.warning(f"Failed to apply patch to {file_path}. Checking if already applied.")
                if self._check_if_patch_already_applied(patch_content, normalized_original_content):
                     self.logger.info(f"Changes for {file_path} appear to be already applied. Skipping.")
                     return False
                else:
                     self.logger.error(f"Failed to apply patch to {file_path} and it does not seem to be applied yet.")
                     return False

        except Exception as e:
            self.logger.error(f"An unexpected error occurred while applying patch to {file_path}: {e}")
            return False
    
    def _check_if_patch_already_applied(self, patch_content: str, current_content: str) -> bool:
        """More robust check to see if patch changes might already be applied or are not needed."""
        try:
            added_lines = []
            removed_lines = []
            
            for line in patch_content.split('\n'):
                if line.startswith('+') and not line.startswith('+++'):
                    added_lines.append(line[1:].strip())
                elif line.startswith('-') and not line.startswith('---'):
                    removed_lines.append(line[1:].strip())

            # Scenario 1: The patch is trying to ADD lines.
            if added_lines and not removed_lines:
                # If all added lines are already present, the patch is applied.
                return all(line in current_content for line in added_lines)
            
            # Scenario 2: The patch is trying to REMOVE lines (a revert).
            if removed_lines and not added_lines:
                # If none of the lines to be removed are present, the revert is already complete.
                return not any(line in current_content for line in removed_lines)
                
            # Scenario 3: The patch is MODIFYING lines (both adds and removes).
            if added_lines and removed_lines:
                # A simple heuristic: if all the additions are present AND none of the removals are,
                # it's highly likely the change has been applied.
                adds_present = all(line in current_content for line in added_lines)
                removals_absent = not any(line in current_content for line in removed_lines)
                return adds_present and removals_absent

            return False
        except Exception as e:
            self.logger.warning(f"Could not determine if patch was already applied: {e}")
            return False
    
    def commit_changes(self, commit_message: str):
        """Stage all changes and commit"""
        try:
            self.repo.git.add('.')
            self.repo.git.commit('-m', commit_message)
            self.logger.info(f"Committed changes: {commit_message}")
        except Exception as e:
            self.logger.error(f"Failed to commit changes: {e}")
            raise
    
    def push_branch(self, branch_name: str):
        """Push the branch to remote, handling both new and existing branches robustly."""
        try:
            # Check if remote branch exists
            try:
                self.logger.info(f"Checking if remote branch {branch_name} exists.")
                self.repo.git.ls_remote('--exit-code', '--heads', 'origin', branch_name)
                remote_branch_exists = True
                self.logger.info(f"Remote branch {branch_name} exists.")
            except Exception:
                remote_branch_exists = False
                self.logger.info(f"Remote branch {branch_name} does not exist.")
            
            if remote_branch_exists:
                # Remote branch exists, pull first to avoid non-fast-forward errors
                self.logger.info(f"Pulling latest changes for existing branch {branch_name}.")
                try:
                    self.repo.git.pull('origin', branch_name)
                except Exception as pull_error:
                    self.logger.warning(f"Pull failed, but continuing with push: {pull_error}")

            # Push the branch
            if remote_branch_exists:
                self.logger.info(f"Pushing branch {branch_name} to remote.")
                self.repo.git.push('origin', branch_name)
            else:
                self.logger.info(f"Pushing new branch {branch_name} to remote with --set-upstream.")
                self.repo.git.push('--set-upstream', 'origin', branch_name)
            
            self.logger.info(f"Successfully pushed branch {branch_name} to remote.")
            
        except Exception as e:
            self.logger.error(f"Failed to push branch {branch_name}: {e}")
            raise

    def find_and_replace_in_file(self, file_path: str, find_regex: str, replace_text: str) -> Tuple[bool, str]:
        """
        Find and replace text in a file using regex patterns
        
        Args:
            file_path: Path to the file relative to workspace
            find_regex: Regex pattern to find
            replace_text: Text to replace it with
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        import re
        
        try:
            full_path = self.workspace_path / file_path
            
            if not full_path.exists():
                return False, f"File {file_path} does not exist"
            
            # Read current content
            with open(full_path, 'r', encoding='utf-8') as f:
                current_content = f.read()
            
            # Compile regex pattern
            try:
                pattern = re.compile(find_regex, re.MULTILINE | re.DOTALL)
            except re.error as e:
                return False, f"Invalid regex pattern: {str(e)}"
            
            # Check if pattern matches
            matches = pattern.findall(current_content)
            if not matches:
                return False, f"Regex pattern not found in {file_path}. Pattern: {find_regex}"
            
            # Check if pattern matches multiple times
            if len(matches) > 1:
                return False, f"Regex pattern matches {len(matches)} times in {file_path}. Please make your pattern more specific to match only one instance."
            
            # Perform replacement
            new_content = pattern.sub(replace_text, current_content)
            
            # Write back to file
            with open(full_path, 'w', encoding='utf-8', newline='') as f:
                f.write(new_content)
            
            self.logger.info(f"Successfully replaced text in {file_path} using regex")
            self.logger.info(f"Regex pattern: {repr(find_regex[:100])}{'...' if len(find_regex) > 100 else ''}")
            self.logger.info(f"Replace text: {repr(replace_text[:100])}{'...' if len(replace_text) > 100 else ''}")
            
            return True, f"Successfully replaced text in {file_path} using regex pattern"
            
        except Exception as e:
            self.logger.error(f"Error in find_and_replace for {file_path}: {e}")
            return False, f"Error replacing text in {file_path}: {str(e)}"


class InstructionManager:
    """Handles loading instruction files for AI agents"""
    
    def __init__(self):
        self.instructions_path = Path("instructions")
        self.logger = logging.getLogger(__name__)
    
    def load_ba_instructions(self) -> str:
        """Load BA agent instructions"""
        try:
            ba_file = self.instructions_path / "ba.md"
            if ba_file.exists():
                return ba_file.read_text(encoding='utf-8')
            else:
                self.logger.warning("BA instructions file not found")
                return ""
        except Exception as e:
            self.logger.error(f"Failed to load BA instructions: {e}")
            return ""
    
    def load_coder_instructions(self) -> str:
        """Load Coder agent instructions"""
        try:
            coder_file = self.instructions_path / "coder.md"
            if coder_file.exists():
                return coder_file.read_text(encoding='utf-8')
            else:
                self.logger.warning("Coder instructions file not found")
                return ""
        except Exception as e:
            self.logger.error(f"Failed to load Coder instructions: {e}")
            return ""


class AIAgent:
    """Handles interactions with Gemini AI API"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        genai.configure(api_key=config.gemini_api_key)
        self.model = genai.GenerativeModel(config.gemini_model)
        self.logger = logging.getLogger(__name__)
    
    def _format_attachments_for_prompt(self, attachments_info: Dict[str, Dict]) -> str:
        """Format attachment information for inclusion in AI prompts"""
        if not attachments_info:
            return "No attachments provided."
        
        formatted = []
        for filename, info in attachments_info.items():
            formatted.append(f"- {filename} ({info['size']} bytes, {info['content_type']})")
        
        return "\n".join(formatted)

    def _extract_json_from_response(self, response_text: str) -> str:
        """Extract JSON content from AI response, handling markdown code fences and other formatting"""
        
        # Remove common markdown patterns
        text = response_text.strip()
        
        # Remove markdown code fences (````json, ```json, ```, etc.)
        patterns = [
            r'^```+\s*json\s*\n',  # Opening: ```json or ````json
            r'^```+\s*\n',         # Opening: ``` or ````
            r'\n```+\s*$',         # Closing: ``` or ````
            r'^```+\s*$',          # Standalone ``` or ````
            r'```+\s*json\s*',     # Any ```json anywhere
            r'```+\s*',            # Any ``` anywhere
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.MULTILINE)
        
        # Remove any leading/trailing whitespace after fence removal
        text = text.strip()
        
        # Find JSON boundaries (first { to last })
        json_start = text.find('{')
        json_end = text.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            json_content = text[json_start:json_end]
            
            # Additional cleanup for common JSON formatting issues
            json_content = json_content.strip()
            
            # Remove any trailing commas before closing braces/brackets
            json_content = re.sub(r',(\s*[}\]])', r'\1', json_content)
            
            # Remove any extra characters after the final }
            final_brace = json_content.rfind('}')
            if final_brace != -1:
                json_content = json_content[:final_brace + 1]
            
            return json_content
        
        # If no JSON boundaries found, return cleaned text and let JSON parser handle the error
        return text

    def invoke_ba_agent(self, ticket: JiraTicket, instructions: str, codebase: str, 
                       temp_artifacts_path: Path, attachments_info: Dict[str, Dict] = None) -> str:
        """
        Invoke the BA agent with ticket and codebase context
        Returns the BA specification as markdown text
        """
        
        try:
            # Prepare prompt with all context
            ticket_context = f"""
JIRA TICKET: {ticket.key}
Summary: {ticket.summary}
Description: {ticket.description}

Comments:
{chr(10).join([f"- {comment}" for comment in ticket.comments])}
"""
            
            # Add attachments information if available
            attachments_context = ""
            if attachments_info:
                attachments_context = f"""
ATTACHMENTS:
{self._format_attachments_for_prompt(attachments_info)}
"""
            
            prompt = f"""
{instructions}

{ticket_context}

{attachments_context}

CODEBASE STRUCTURE AND CONTENT:
{codebase}

Please provide your business analysis following the markdown format specified in the instructions.
"""
            
            # Create Gemini request
            request_data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.5,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 65535
                }
            }
            
            # Make API call
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={self.config.gemini_api_key}",
                headers={"Content-Type": "application/json"},
                json=request_data,
                timeout=180
            )
            
            if response.status_code != 200:
                raise ValueError(f"Gemini API error: {response.status_code} - {response.text}")
            
            response_data = response.json()
            if 'candidates' not in response_data or not response_data['candidates']:
                raise ValueError(f"No response from Gemini API: {response_data}")
            
            response_text = response_data['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Write raw response to log file
            log_file_path = temp_artifacts_path / f"{ticket.key}_ba_response.txt"
            with open(log_file_path, "w", encoding="utf-8") as log_file:
                log_file.write(response_text)
            
            self.logger.info("BA Agent generated specification successfully")
            return response_text
            
        except Exception as e:
            self.logger.error(f"BA Agent invocation failed: {e}")
            raise ValueError(f"BA Agent failed: {e}")
    
    def invoke_coding_agent_iterative(self, ticket: JiraTicket, ba_spec: str, 
                                      instructions: str, git_manager: 'GitManager', 
                                      temp_artifacts_path: Path) -> List[Dict[str, Any]]:
        """Invoke the Coding Agent with iterative conversation approach"""
        
        file_changes = []
        conversation_history = []  # Track only assistant responses and system messages
        provided_files = {}  # Cache of files already provided to agent {file_path: content}
        file_modification_tracking = {}  # Track if files were modified since last provided
        last_get_file_request = None  # Algorithmic restraint to prevent infinite loops
        last_replace_operation = None  # Track last replace operation to prevent loops
        turn_number = 1
        
        try:
            while True:
                self.logger.info(f"Coding Agent conversation turn {turn_number}")
                
                # Build context for this turn with project structure but not full content
                full_context = f"""You are an expert Coding Agent. Follow the instructions below to implement the changes specified in the BA specification.

**INSTRUCTIONS:**
{instructions}

**ORIGINAL JIRA TICKET:**
- Key: {ticket.key}
- Summary: {ticket.summary}
- Description: {ticket.description}
- Comments: {chr(10).join(f"- {comment}" for comment in ticket.comments)}

**BA SPECIFICATION:**
{ba_spec}

**PROJECT STRUCTURE:**
{git_manager.get_codebase_structure()}

**IMPORTANT NOTES:**
- You have access to the complete project structure above
- **MANDATORY: Review ALL files listed in the BA's "Files to Review" section FIRST** - these show you the correct patterns and examples
- Use "get_file" operation to request specific files you need to examine in detail
- Use "find_and_replace" operation for precise modifications using regex patterns
- Work incrementally: examine reference files first, understand patterns, then make targeted changes
- **For text replacements**: Use regex patterns to find and replace content flexibly, handling variations in whitespace and formatting

--- CONVERSATION HISTORY ---
{chr(10).join(conversation_history) if conversation_history else "No previous conversation."}
--- END CONVERSATION HISTORY ---

Start by requesting the files you need to examine, then make the necessary changes. Signal completion when all BA requirements are fulfilled."""
                
                response = self.model.generate_content(full_context)
                response_text = response.text.strip()
                
                # Log this turn's response
                turn_log_file = temp_artifacts_path / f"{ticket.key}_coder_turn_{turn_number}.txt"
                with open(turn_log_file, 'w', encoding='utf-8') as f:
                    f.write(response_text)
                
                self.logger.info(f"Coding Agent turn {turn_number} response logged to {turn_log_file}")
                
                # Check for completion signal
                is_complete = False
                completion_summary = ""
                
                # Method 1: Plain "CHANGES DONE" string
                if response_text.strip() == "CHANGES DONE":
                    is_complete = True
                
                # Method 2: "CHANGES DONE" anywhere in the response (case insensitive)
                elif "CHANGES DONE" in response_text.upper():
                    is_complete = True
                    # Try to extract summary from plain text format
                    if "Summary:" in response_text:
                        summary_start = response_text.find("Summary:")
                        completion_summary = response_text[summary_start:].strip()
                
                # Method 3: JSON with operation "complete"
                else:
                    try:
                        json_content = self._extract_json_from_response(response_text)
                        parsed_response = json.loads(json_content)
                        if parsed_response.get('operation') == 'complete':
                            # Before accepting completion, validate any HTML files that were modified
                            html_validation_errors = []
                            for change in file_changes:
                                if change.get('file_path', '').endswith(('.htm', '.html')):
                                    file_path = change.get('file_path')
                                    try:
                                        current_content = git_manager.get_file_content(file_path)
                                        if current_content:
                                            # Check for orphaned closing tags
                                            if '</header>' in current_content and '<header' not in current_content:
                                                html_validation_errors.append(f"{file_path}: orphaned </header> tag")
                                            if '</nav>' in current_content and '<nav' not in current_content:
                                                html_validation_errors.append(f"{file_path}: orphaned </nav> tag")
                                            if '</section>' in current_content and '<section' not in current_content:
                                                html_validation_errors.append(f"{file_path}: orphaned </section> tag")
                                    except Exception as e:
                                        self.logger.warning(f"Could not validate HTML file {file_path}: {e}")
                            
                            if html_validation_errors:
                                self.logger.error(f"HTML validation failed on completion: {html_validation_errors}")
                                conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                conversation_history.append(f"SYSTEM ERROR: Cannot complete - HTML validation failed. The following files have structural errors: {'; '.join(html_validation_errors)}. Please fix these issues before completing.")
                                continue
                            
                            is_complete = True
                            # Extract summary from JSON
                            completion_summary = parsed_response.get('summary', '')
                    except:
                        pass  # Not a valid JSON completion, continue with normal processing
                
                if is_complete:
                    self.logger.info("Coding Agent signaled completion")
                    break
                
                # Extract and parse the operation instruction
                try:
                    # Extract JSON from response, handling any surrounding text
                    json_content = self._extract_json_from_response(response_text)
                    operation_request = json.loads(json_content)
                    
                    # Validate operation format
                    if not self._validate_operation_request(operation_request):
                        raise ValueError("Invalid operation format")
                    
                    operation = operation_request.get('operation', 'write_file')
                    
                    # Handle different operation types
                    if operation == 'get_file':
                        # Handle file request
                        file_path = operation_request.get('file_path')
                        reason = operation_request.get('reason', 'File requested')
                        
                        self.logger.info(f"Coding agent requested file: {file_path} - {reason}")
                        
                        # Algorithmic restraint: prevent infinite loops
                        if last_get_file_request == file_path and file_path not in file_modification_tracking:
                            self.logger.warning(f"Agent requested same file '{file_path}' twice in a row without changes - terminating to prevent loop")
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM: AUTOMATIC TERMINATION - You requested the same file '{file_path}' twice in a row without making any changes. This suggests you may be stuck in a loop. Please review the BA specification and focus on the specific task requirements.")
                            break
                        
                        last_get_file_request = file_path
                        
                        # Check if file was already provided and hasn't been modified
                        if (file_path in provided_files and 
                            file_path not in file_modification_tracking):
                            
                            # File already provided and hasn't been modified since
                            self.logger.info(f"File {file_path} already provided in this conversation")
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM: File '{file_path}' was already provided earlier in this conversation and hasn't been modified since. The content remains:\n\n```\n{provided_files[file_path]}\n```\n\nPlease proceed with your changes or request a different file if needed.")
                        
                        else:
                            # Get fresh file content
                            try:
                                file_content = git_manager.get_file_content(file_path)
                                if file_content is not None:
                                    # Cache the file content
                                    provided_files[file_path] = file_content
                                    # Clear modification tracking since we're providing fresh content
                                    file_modification_tracking.pop(file_path, None)
                                    
                                    # Add file content to conversation history
                                    conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                    conversation_history.append(f"SYSTEM: File '{file_path}' content:\n\n```\n{file_content}\n```\n\nWhat would you like to do with this file?")
                                else:
                                    conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                    conversation_history.append(f"SYSTEM ERROR: File '{file_path}' not found. Please check the file path or create the file if needed.")
                            except Exception as e:
                                conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                conversation_history.append(f"SYSTEM ERROR: Could not read file '{file_path}': {str(e)}")
                    
                    elif operation == 'replace_lines':
                        # Handle line replacement
                        file_path = operation_request.get('file_path')
                        start_line = operation_request.get('start_line')
                        end_line = operation_request.get('end_line')
                        new_content = operation_request.get('new_content', '')
                        
                        self.logger.info(f"Coding agent replacing lines {start_line}-{end_line} in {file_path}")
                        
                        # Algorithmic restraint: prevent infinite loops for replace_lines
                        if (last_replace_operation and 
                            last_replace_operation.get('operation') == 'replace_lines' and
                            last_replace_operation.get('file_path') == file_path and
                            last_replace_operation.get('start_line') == start_line and
                            last_replace_operation.get('end_line') == end_line and
                            last_replace_operation.get('new_content') == new_content):
                            
                            self.logger.warning(f"Agent repeated same replace_lines operation - terminating to prevent loop")
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM: AUTOMATIC TERMINATION - You repeated the same replace_lines operation. This suggests you may be stuck in a loop. Please review the current file state and try a different approach or signal completion with 'CHANGES DONE'.")
                            break
                        
                        # Prevent massive replacements that could corrupt file structure
                        lines_to_replace = end_line - start_line + 1
                        if lines_to_replace > 50:  # More than 50 lines
                            self.logger.warning(f"Agent attempting to replace {lines_to_replace} lines - this may indicate confusion about file structure")
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM: WARNING - You're attempting to replace {lines_to_replace} lines. This is a very large change that may corrupt the file structure. Consider using smaller, more targeted replacements or 'create_file' if you need to rewrite most of the file. Please reconsider your approach.")
                            continue
                        
                        try:
                            success, updated_content = git_manager.replace_file_lines(file_path, start_line, end_line, new_content)
                            if success:
                                file_changes.append(operation_request)
                                
                                # Update file cache with new content
                                provided_files[file_path] = updated_content
                                # Mark file as modified so agent knows it's been changed
                                file_modification_tracking[file_path] = True
                                # Reset loop detection since agent made a change
                                last_get_file_request = None
                                last_replace_operation = operation_request
                                
                                conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                conversation_history.append(f"SYSTEM: Successfully replaced lines {start_line}-{end_line} in '{file_path}'. Updated file content:\n\n```\n{updated_content}\n```\n\nIs there anything else needed to fulfill the BA specification, or are you ready to respond with 'CHANGES DONE'?")
                            else:
                                conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                conversation_history.append(f"SYSTEM ERROR: Failed to replace lines {start_line}-{end_line} in '{file_path}'. Please check line numbers and try again.")
                        except Exception as e:
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM ERROR: Could not replace lines in '{file_path}': {str(e)}")
                    
                    elif operation == 'find_and_replace':
                        # Handle find and replace operation
                        file_path = operation_request.get('file_path')
                        find_regex = operation_request.get('find_regex')
                        replace_text = operation_request.get('replace_text')
                        reason = operation_request.get('reason', 'Text replacement')
                        
                        self.logger.info(f"Coding agent find_and_replace in {file_path}: {reason}")
                        
                        # Validate required parameters
                        if not file_path or find_regex is None or replace_text is None:
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM ERROR: find_and_replace operation requires 'file_path', 'find_regex', and 'replace_text' parameters.")
                            continue
                        
                        # Algorithmic restraint: prevent infinite loops for find_and_replace
                        if (last_replace_operation and 
                            last_replace_operation.get('operation') == 'find_and_replace' and
                            last_replace_operation.get('file_path') == file_path and
                            last_replace_operation.get('find_regex') == find_regex and
                            last_replace_operation.get('replace_text') == replace_text):
                            
                            self.logger.warning(f"Agent repeated same find_and_replace operation - terminating to prevent loop")
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM: AUTOMATIC TERMINATION - You repeated the same find_and_replace operation. This suggests you may be stuck in a loop. Please review the current file state and try a different approach or signal completion with 'CHANGES DONE'.")
                            break
                        
                        try:
                            success, message = git_manager.find_and_replace_in_file(file_path, find_regex, replace_text)
                            if success:
                                file_changes.append(operation_request)
                                
                                # Get updated file content for cache
                                updated_content = git_manager.get_file_content(file_path)
                                if updated_content is not None:
                                    # Update file cache with new content
                                    provided_files[file_path] = updated_content
                                    # Mark file as modified so agent knows it's been changed
                                    file_modification_tracking[file_path] = True
                                    # Reset loop detection since agent made a change
                                    last_get_file_request = None
                                    last_replace_operation = operation_request
                                    
                                    conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                    conversation_history.append(f"SYSTEM: Successfully replaced text in '{file_path}'. Updated file content:\n\n```\n{updated_content}\n```\n\nIs there anything else needed to fulfill the BA specification, or are you ready to respond with 'CHANGES DONE'?")
                                else:
                                    conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                    conversation_history.append(f"SYSTEM: Text replacement succeeded but could not read updated file content. Please verify the change was applied correctly.")
                            else:
                                conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                                conversation_history.append(f"SYSTEM ERROR: {message}")
                        except Exception as e:
                            conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                            conversation_history.append(f"SYSTEM ERROR: Could not perform find_and_replace in '{file_path}': {str(e)}")
                    
                    else:
                        # Handle traditional file operations (write_file, create_file, delete_file, copy_file)
                        file_changes.append(operation_request)
                    
                    # Log received operation based on type
                    if operation == 'copy_file':
                        source_path = operation_request.get('source_path')
                        target_path = operation_request.get('target_path')
                        self.logger.info(f"Received {operation} operation: {source_path} -> {target_path}")
                        
                        # Update cache for copied file - remove it since we don't know the new content without reading
                        if target_path in provided_files:
                            del provided_files[target_path]
                        file_modification_tracking[target_path] = True
                        
                        conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                        conversation_history.append(f"SYSTEM: {operation} operation for '{source_path}' -> '{target_path}' completed successfully. Is there anything else needed to fulfill the BA specification, or are you ready to respond with 'CHANGES DONE'?")
                        
                    elif operation in ['write_file', 'create_file']:
                        file_path = operation_request.get('file_path')
                        file_content = operation_request.get('file_content', '')
                        self.logger.info(f"Received {operation} operation for: {file_path}")
                        
                        # Update cache with new content for write/create operations
                        provided_files[file_path] = file_content
                        file_modification_tracking[file_path] = True
                        
                        conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                        conversation_history.append(f"SYSTEM: {operation} operation for '{file_path}' completed successfully. Is there anything else needed to fulfill the BA specification, or are you ready to respond with 'CHANGES DONE'?")
                        
                    elif operation == 'delete_file':
                        file_path = operation_request.get('file_path')
                        self.logger.info(f"Received {operation} operation for: {file_path}")
                        
                        # Remove from cache since file is deleted
                        if file_path in provided_files:
                            del provided_files[file_path]
                        file_modification_tracking.pop(file_path, None)
                        
                        conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                        conversation_history.append(f"SYSTEM: {operation} operation for '{file_path}' completed successfully. Is there anything else needed to fulfill the BA specification, or are you ready to respond with 'CHANGES DONE'?")
                    
                    else:
                        # Unknown operation
                        conversation_history.append(f"ASSISTANT TURN {turn_number}: {response_text}")
                        conversation_history.append(f"SYSTEM ERROR: Unknown operation '{operation}'. Supported operations: get_file, find_and_replace, write_file, create_file, delete_file, copy_file, complete.")
                    
                except json.JSONDecodeError as e:
                    self.logger.error(f"Turn {turn_number}: Invalid JSON response: {str(e)}")
                    # Don't log raw response to avoid Unicode encoding issues
                    conversation_history.append(f"ASSISTANT TURN {turn_number}: [Response contained invalid JSON]")
                    conversation_history.append(f"SYSTEM ERROR: Invalid JSON format. Please provide a valid JSON response with 'operation' and required fields (get_file: file_path; find_and_replace: file_path/find_regex/replace_text; write_file/create_file: file_path/file_content; copy_file: source_path/target_path), or 'CHANGES DONE' if all BA requirements are fulfilled.")
                
                except ValueError as e:
                    self.logger.error(f"Turn {turn_number}: Invalid operation format: {str(e)}")
                    conversation_history.append(f"ASSISTANT TURN {turn_number}: [Response contained invalid operation]")
                    conversation_history.append(f"SYSTEM ERROR: Invalid operation format. Please provide JSON with 'operation' (get_file/find_and_replace/write_file/create_file/delete_file/copy_file) and required fields, or 'CHANGES DONE' if all BA requirements are fulfilled.")
                
                turn_number += 1
                
                # Safety limit to prevent infinite loops
                if turn_number > 20:
                    self.logger.warning("Reached maximum conversation turns (20), stopping")
                    break
            
            self.logger.info(f"Coding Agent conversation completed after {turn_number-1} turns with {len(file_changes)} file changes")
            
            # Return both file changes and completion summary
            return {
                'file_changes': file_changes,
                'completion_summary': completion_summary
            }
            
        except Exception as e:
            self.logger.error(f"Coding Agent iterative invocation failed: {e}")
            return []
    
    def _validate_operation_request(self, operation_request: Dict) -> bool:
        """Validate that operation request has required fields for the specified operation"""
        if not isinstance(operation_request, dict):
            return False
        
        operation = operation_request.get('operation', 'write_file')  # Default to write_file for backward compatibility
        
        # Validate based on operation type
        if operation == 'get_file':
            # Get file operations only need file_path
            file_path = operation_request.get('file_path')
            return file_path and isinstance(file_path, str)
        
        elif operation == 'replace_lines':
            # Replace lines operations need file_path, start_line, end_line, and new_content
            file_path = operation_request.get('file_path')
            start_line = operation_request.get('start_line')
            end_line = operation_request.get('end_line')
            new_content = operation_request.get('new_content')
            return (file_path and isinstance(file_path, str) and
                   isinstance(start_line, int) and start_line > 0 and
                   isinstance(end_line, int) and end_line > 0 and
                   start_line <= end_line and
                   new_content is not None and isinstance(new_content, str))
        
        elif operation in ['write_file', 'create_file']:
            # These operations require file_path and file_content
            file_path = operation_request.get('file_path')
            file_content = operation_request.get('file_content')
            return (file_path and isinstance(file_path, str) and 
                   file_content is not None and isinstance(file_content, str))
        
        elif operation == 'delete_file':
            # Delete operations only need file_path
            file_path = operation_request.get('file_path')
            return file_path and isinstance(file_path, str)
        
        elif operation == 'copy_file':
            # Copy operations need source_path and target_path
            source_path = operation_request.get('source_path')
            target_path = operation_request.get('target_path')
            return (source_path and isinstance(source_path, str) and
                   target_path and isinstance(target_path, str))
        
        elif operation == 'find_and_replace':
            # Find and replace operations need file_path, find_regex, and replace_text
            file_path = operation_request.get('file_path')
            find_regex = operation_request.get('find_regex')
            replace_text = operation_request.get('replace_text')
            return (file_path and isinstance(file_path, str) and
                   find_regex is not None and isinstance(find_regex, str) and
                   replace_text is not None and isinstance(replace_text, str))
        
        else:
            # Unknown operation
            return False

    def invoke_coding_agent(self, ticket: JiraTicket, ba_spec: str,
                           instructions: str, codebase: Dict[str, str], temp_artifacts_path: Path) -> List[Dict[str, str]]:
        """Invoke the Coding Agent with comprehensive context (LEGACY - kept for compatibility)"""
        
        # Prepare codebase section for context
        codebase_section = self._format_codebase_for_prompt(codebase)
        
        prompt = f"""You are an expert Coding Agent. Follow the instructions below to implement the changes specified in the BA specification.

**INSTRUCTIONS:**
{instructions}

**ORIGINAL JIRA TICKET:**
- Key: {ticket.key}
- Summary: {ticket.summary}
- Description: {ticket.description}
- Comments: {chr(10).join(f"- {comment}" for comment in ticket.comments)}

**BA SPECIFICATION:**
{ba_spec}

**CURRENT CODEBASE CONTENT:**
{codebase_section}

Based on the BA specification and current codebase, produce ONLY the JSON object with unified diff patches as defined in your instructions. No additional text or explanation."""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Log full response to temp_artifacts (before any processing)
            coder_log_file = temp_artifacts_path / f"{ticket.key}_coder_response.txt"
            with open(coder_log_file, 'w', encoding='utf-8') as f:
                f.write(response_text)
            
            self.logger.info(f"Coding Agent response logged to {coder_log_file}")
            
            # Extract JSON content using robust method
            json_content = self._extract_json_from_response(response_text)
            
            # Attempt to fix unescaped quotes before parsing
            cleaned_json = self._fix_unescaped_quotes(json_content)
            
            # Parse JSON response
            changes = json.loads(cleaned_json)
            self.logger.info("Coding Agent generated changes successfully")
            return changes
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Coding Agent returned invalid JSON: {e}")
            self.logger.error(f"Raw response: {response_text}")
            self.logger.error(f"Cleaned response (attempted fix): {cleaned_json}")
            raise ValueError(f"Coding Agent returned invalid JSON: {e}")
        except Exception as e:
            self.logger.error(f"Coding Agent invocation failed: {e}")
            raise
    
    def _format_codebase_for_prompt(self, codebase: Dict[str, str]) -> str:
        """Format codebase contents for AI prompt"""
        sections = []
        
        for file_path, content in codebase.items():
            # Truncate very long files to prevent token limits
            if len(content) > 10000:
                content = content[:10000] + f"\n\n... [FILE TRUNCATED - {len(content)} total characters] ..."
            
            sections.append(f"""---
FILE: {file_path}
---
{content}
""")
        
        return "\n".join(sections)


class LocalServerManager:
    """Handles local development server for testing changes"""
    
    def __init__(self, workspace_path: Path, port: int = 777):
        self.workspace_path = workspace_path
        self.port = port
        self.server = None
        self.server_thread = None
        self.logger = logging.getLogger(__name__)
    
    def is_port_available(self) -> bool:
        """Check if the specified port is available"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', self.port))
                return True
        except OSError:
            return False
    
    def find_available_port(self) -> int:
        """Find an available port starting from the preferred port"""
        for port in range(self.port, self.port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('localhost', port))
                    return port
            except OSError:
                continue
        raise Exception("No available ports found")
    
    def start_server(self) -> str:
        """Start the local development server"""
        try:
            # Ensure workspace directory exists and is accessible
            if not self.workspace_path.exists():
                raise Exception(f"Workspace directory does not exist: {self.workspace_path}")
            
            # Kill any existing processes on the port (more aggressive cleanup)
            self.logger.info(f"Cleaning up any existing processes on port {self.port}")
            os.system(f"netstat -ano | findstr :{self.port} > nul && (for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{self.port} ^| findstr LISTENING') do taskkill /f /pid %a 2>nul) || echo No processes found on port {self.port}")
            
            # Wait a moment for cleanup
            time.sleep(0.5)
            
            # Find available port
            if not self.is_port_available():
                actual_port = self.find_available_port()
                self.logger.warning(f"Port {self.port} is busy, using port {actual_port}")
                self.port = actual_port
            
            # Create server, passing the workspace_path explicitly to the handler
            try:
                # This lambda creates a handler that serves files from the specified directory
                # without changing the current working directory of the script.
                handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=self.workspace_path.as_posix(), **kwargs)
                self.server = HTTPServer(('localhost', self.port), handler)
                self.logger.info(f"Created HTTP server on localhost:{self.port}, serving from {self.workspace_path.absolute()}")
            except Exception as e:
                self.logger.error(f"Failed to create HTTP server: {e}")
                raise
            
            # Start server in a separate thread
            def run_server():
                try:
                    self.logger.info(f"Starting local server thread on http://localhost:{self.port}")
                    self.server.serve_forever()
                except Exception as e:
                    self.logger.error(f"Server thread error: {e}")
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            
            # Give server more time to start and verify it's running
            time.sleep(2)
            
            # Verify server is actually running
            if not self.server_thread.is_alive():
                raise Exception("Server thread failed to start")
            
            # Test if server is responding
            server_url = f"http://localhost:{self.port}"
            try:
                import urllib.request
                urllib.request.urlopen(server_url, timeout=5)
                self.logger.info(f"Server verified and responding at {server_url}")
            except Exception as e:
                self.logger.warning(f"Server may not be responding yet: {e}")
            
            self.logger.info(f"Local development server started at {server_url}")
            return server_url
            
        except Exception as e:
            self.logger.error(f"Failed to start local server: {e}")
            raise

    def stop_server(self):
        """Stop the local development server"""
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
                self.logger.info("Local development server stopped")
            except Exception as e:
                self.logger.error(f"Error stopping server: {e}")
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
    
    def get_server_url(self) -> Optional[str]:
        """Get the current server URL if running"""
        if self.server:
            return f"http://localhost:{self.port}"
        return None


class OrchestratorScript:
    """Main orchestrator class that coordinates the entire workflow"""
    
    @staticmethod
    def clean_temp_artifacts_early():
        """Clean temp artifacts and attachments before logging is initialized to avoid file locks"""
        temp_artifacts_path = Path("temp_artifacts")
        attachments_path = Path("attachments")
        
        for path in [temp_artifacts_path, attachments_path]:
            if not path.exists():
                continue
            
            for item in path.iterdir():
                try:
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                    # No logging here since logger isn't set up yet
                except OSError:
                    # Silently continue - we'll log properly later
                    pass
    
    def __init__(self):
        self.setup_logging()
        self.logger = logging.getLogger(__name__)
        
        # Create temp_artifacts directory for logs and generated files
        self.temp_artifacts_path = Path("temp_artifacts")
        self.temp_artifacts_path.mkdir(exist_ok=True)
        
        # Create attachments directory for Jira ticket attachments
        self.attachments_path = Path("attachments")
        self.attachments_path.mkdir(exist_ok=True)
        
        try:
            self.config = ConfigManager()
            self.jira_manager = JiraManager(self.config)
            self.git_manager = GitManager(self.config)
            self.ai_agent = AIAgent(self.config)
            self.instruction_manager = InstructionManager()
            self.server_manager = None
        except Exception as e:
            self.logger.error(f"Failed to initialize orchestrator: {e}")
            sys.exit(1)
    
    def setup_logging(self):
        """Configure logging"""
        # Ensure temp_artifacts directory exists
        temp_artifacts_path = Path("temp_artifacts")
        temp_artifacts_path.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler(temp_artifacts_path / 'orchestrator.log')
            ]
        )
    
    def handle_failure(self, ticket_key: str, error_message: str):
        """Handle failure by updating Jira ticket"""
        try:
            self.jira_manager.add_comment(ticket_key, f"Automated processing failed: {error_message}")
            # Transition to "Pending" on failure/error (allows for retry)
            self.jira_manager.transition_ticket(ticket_key, "Pending")
            self.logger.error(f"Marked ticket {ticket_key} as pending due to: {error_message}")
        except Exception as e:
            self.logger.error(f"Failed to update ticket {ticket_key} with pending status: {e}")
        
        # Stop server if running
        if self.server_manager:
            self.server_manager.stop_server()
    
    def _has_uncommitted_changes(self) -> bool:
        """Check if there are any uncommitted changes in the Git repository"""
        try:
            # Check for staged changes
            staged_changes = bool(self.git_manager.repo.git.diff('--cached'))
            # Check for unstaged changes
            unstaged_changes = bool(self.git_manager.repo.git.diff())
            # Check for untracked files
            untracked_files = bool(self.git_manager.repo.git.ls_files('--others', '--exclude-standard'))
            
            return staged_changes or unstaged_changes or untracked_files
        except Exception as e:
            self.logger.warning(f"Error checking for uncommitted changes: {e}")
            return False
    
    def _clean_old_workspaces(self):
        """Deletes old workspace directories based on a predefined pattern."""
        self.logger.info("Starting to clean old workspace directories.")
        current_dir = Path(".")
        
        for item in current_dir.iterdir():
            if item.is_dir() and (item.name.startswith("workspace") or item.name == "workspace"):
                self.logger.info(f"Attempting to delete old workspace: {item.name}")
                
                # First, try to cleanup any Git repository in the directory
                try:
                    if (item / ".git").exists():
                        self.logger.info(f"Found Git repository in {item.name}, cleaning up Git processes...")
                        # Try to close any open Git repository
                        try:
                            temp_repo = Repo(str(item))
                            temp_repo.close()
                            del temp_repo
                        except:
                            pass
                        
                        # Force kill any git processes that might be locking files
                        os.system("taskkill /f /im git.exe 2>nul")
                        os.system("taskkill /f /im python.exe /fi \"WINDOWTITLE eq *workspace*\" 2>nul")
                        time.sleep(0.5)
                except Exception as e:
                    self.logger.warning(f"Error during Git cleanup for {item.name}: {e}")
                
                # Now try to delete the directory
                try:
                    # On Windows, use rmdir with force flag via system command as fallback
                    if os.name == 'nt':  # Windows
                        result = os.system(f'rmdir /s /q "{item}"')
                        if result == 0:
                            self.logger.info(f"Successfully deleted {item.name} using system command")
                        else:
                            # Fallback to Python shutil
                            shutil.rmtree(item, ignore_errors=True)
                            if not item.exists():
                                self.logger.info(f"Successfully deleted {item.name} using shutil fallback")
                            else:
                                self.logger.error(f"Failed to delete {item.name} - directory may be in use")
                    else:
                        # Non-Windows systems
                        shutil.rmtree(item)
                        self.logger.info(f"Successfully deleted {item.name}")
                        
                except OSError as e:
                    self.logger.error(f"Failed to delete {item.name}: {e}")
                    self.logger.error(f"Please manually delete the directory or ensure no processes are using files within it")

    def run(self):
        """Main execution logic"""
        self.logger.info("Starting enhanced orchestrator script")
        self.logger.info("Temporary artifacts cleaned before logging initialization")

        try:
            # 0. Clean old workspaces
            self._clean_old_workspaces()

            # 1. Fetch Task
            self.logger.info("Fetching oldest open Jira ticket")
            ticket = self.jira_manager.get_oldest_open_ticket()
            
            if not ticket:
                self.logger.info("No open tickets found. Exiting.")
                return

            # Transition ticket to "In Progress" as soon as it's picked up
            self.jira_manager.transition_ticket(ticket.key, "In Progress")
            self.logger.info(f"Ticket {ticket.key} status transitioned to 'In Progress'")
            
            self.logger.info(f"Processing ticket: {ticket.key} - {ticket.summary}")
            if ticket.specified_branch:
                self.logger.info(f"Ticket specifies branch: {ticket.specified_branch}")
            
            # 1.5. Download ticket attachments
            self.logger.info("Downloading ticket attachments")
            attachments_info = self.jira_manager.download_ticket_attachments(ticket.key, self.attachments_path)
            if attachments_info:
                self.logger.info(f"Downloaded {len(attachments_info)} attachment(s)")
            
            # 2. Prepare Workspace with specified or main branch
            self.logger.info("Preparing Git workspace")
            self.git_manager.prepare_workspace(ticket.specified_branch)
            
            # 3. Create feature branch and update Jira immediately
            self.logger.info("Creating feature branch")
            feature_branch_name = self.git_manager.create_feature_branch(ticket.key)
            
            # Note: Branch comment will be added AFTER successful push to remote
            self.logger.info(f"Created feature branch: {feature_branch_name}")
            
            # 4. Load full codebase context for BA Agent only
            self.logger.info("Loading complete codebase context for BA Agent")
            codebase_contents = self.git_manager.get_all_file_contents()
            
            # 5. Load instruction files
            self.logger.info("Loading instruction files")
            ba_instructions = self.instruction_manager.load_ba_instructions()
            coder_instructions = self.instruction_manager.load_coder_instructions()
            
            # 6. Invoke BA Agent with full context (BA still needs full context to understand project structure)
            self.logger.info("Invoking Business Analyst Agent with full codebase context")
            try:
                ba_spec = self.ai_agent.invoke_ba_agent(ticket, ba_instructions, codebase_contents, self.temp_artifacts_path, attachments_info)
                
                # Add BA specification to Jira as comment
                ba_spec_comment = f"""**Business Analyst Specification Generated:**

{ba_spec}

---"""
                self.jira_manager.add_comment(ticket.key, ba_spec_comment)
                self.logger.info("Added BA specification to Jira ticket")
                
            except Exception as e:
                self.handle_failure(ticket.key, f"BA Agent failed: {str(e)}")
                return
            
            # 7. Invoke Coding Agent with new request-based approach (no full codebase upfront)
            self.logger.info("Invoking Coding Agent with request-based file access")
            try:
                coding_result = self.ai_agent.invoke_coding_agent_iterative(
                    ticket, ba_spec, coder_instructions, self.git_manager, self.temp_artifacts_path
                )
                
                # Extract file changes and completion summary
                coding_changes = coding_result.get('file_changes', [])
                completion_summary = coding_result.get('completion_summary', '')
                
            except Exception as e:
                self.handle_failure(ticket.key, f"Coding Agent failed: {str(e)}")
                return
            
            # 8. Apply Code Changes
            self.logger.info("Applying code changes")
            try:
                successful_operations = []
                failed_operations = []
                
                # Apply each file operation
                if coding_changes:
                    for change in coding_changes:
                        operation = change.get('operation', 'write_file')  # Default for backward compatibility
                        
                        success = False
                        
                        if operation == 'write_file':
                            file_path = change.get('file_path')
                            file_content = change.get('file_content')
                            if not file_path:
                                failed_operations.append(f"unknown: Missing file_path for write_file operation")
                                continue
                            if file_content is None:
                                failed_operations.append(f"{file_path}: Missing file_content for write_file operation")
                                continue
                            success = self.git_manager.write_file_content(file_path, file_content)
                            
                        elif operation == 'create_file':
                            file_path = change.get('file_path')
                            file_content = change.get('file_content')
                            if not file_path:
                                failed_operations.append(f"unknown: Missing file_path for create_file operation")
                                continue
                            if file_content is None:
                                failed_operations.append(f"{file_path}: Missing file_content for create_file operation")
                                continue
                            success = self.git_manager.create_file(file_path, file_content)
                            
                        elif operation == 'delete_file':
                            file_path = change.get('file_path')
                            if not file_path:
                                failed_operations.append(f"unknown: Missing file_path for delete_file operation")
                                continue
                            success = self.git_manager.delete_file(file_path)
                            
                        elif operation == 'copy_file':
                            source_path = change.get('source_path')
                            target_path = change.get('target_path')
                            if source_path is None or target_path is None:
                                failed_operations.append(f"{target_path or source_path or 'unknown'}: Missing source_path or target_path for copy_file operation")
                                continue
                            success = self.git_manager.copy_file(source_path, target_path, self.attachments_path)
                            
                        else:
                            failed_operations.append(f"unknown: Unknown operation '{operation}'")
                            continue
                        
                        if success:
                            if operation == 'copy_file':
                                successful_operations.append(f"{operation}:{source_path}->{target_path}")
                            elif operation in ['write_file', 'create_file', 'delete_file']:
                                successful_operations.append(f"{operation}:{file_path}")
                            else:
                                successful_operations.append(f"{operation}:unknown")
                        else:
                            if operation == 'copy_file':
                                failed_operations.append(f"{target_path}: {operation} operation failed")
                            elif operation in ['write_file', 'create_file', 'delete_file']:
                                failed_operations.append(f"{file_path}: {operation} operation failed")
                            else:
                                failed_operations.append(f"unknown: {operation} operation failed")
                
                # Log results
                if successful_operations:
                    self.logger.info(f"Successfully completed operations: {', '.join(successful_operations)}")
                if failed_operations:
                    self.logger.warning(f"Failed operations: {', '.join(failed_operations)}")
                
                # Only commit if we have some changes (either successful operations or existing changes)
                if successful_operations or self._has_uncommitted_changes():
                    # Commit changes
                    commit_message = f"feat({ticket.key}): {ticket.summary}"
                    if failed_operations:
                        commit_message += f" (partial - {len(failed_operations)} operations failed)"
                    
                    try:
                        self.git_manager.commit_changes(commit_message)
                        
                        # Push branch
                        self.git_manager.push_branch(feature_branch_name)
                        
                        # Add branch comment AFTER successful push to remote
                        branch_comment = f"Processing started. Created and pushed feature branch: {feature_branch_name}"
                        self.jira_manager.add_comment(ticket.key, branch_comment)
                        self.logger.info("Added branch information to Jira ticket after successful push")
                        
                        if failed_operations:
                            # Add comment about partial success
                            partial_comment = f"Implementation partially completed. {len(successful_operations)} changes applied successfully, {len(failed_operations)} failed (possibly already applied)."
                            self.jira_manager.add_comment(ticket.key, partial_comment)
                    except Exception as commit_error:
                        if "nothing to commit" in str(commit_error).lower():
                            self.logger.info("No new changes to commit - all changes appear to already be applied")
                        else:
                            raise commit_error
                else:
                    self.logger.info("No changes to commit - all patches either failed or were already applied")
                    # Add branch comment even if no changes were made
                    branch_comment = f"Processing started. Created and pushed feature branch: {feature_branch_name}"
                    self.jira_manager.add_comment(ticket.key, branch_comment)
                    self.logger.info("Added branch information to Jira ticket (no changes needed)")
                    
                    # Still update Jira to indicate processing was attempted
                    no_changes_comment = f"Processing completed - no new changes needed. All requested modifications appear to already be in place."
                    self.jira_manager.add_comment(ticket.key, no_changes_comment)
                
            except Exception as e:
                self.handle_failure(ticket.key, f"Git operations failed: {str(e)}")
                return
            
            # 9. Launch Local Development Server
            self.logger.info("Starting local development server for testing")
            server_url = None
            try:
                self.server_manager = LocalServerManager(self.git_manager.workspace_path, port=777)
                server_url = self.server_manager.start_server()
                
                # Add server info to Jira comment
                server_comment = f"Local development server started at: {server_url}\n\nYou can now test the changes locally before reviewing the pull request."
                self.jira_manager.add_comment(ticket.key, server_comment)
                
            except Exception as e:
                self.logger.error(f"Failed to start local server: {e}")
                self.logger.info("Continuing without local server - you can manually test the changes in the workspace")
                
                # Add fallback comment to Jira
                fallback_comment = f"Implementation completed successfully but local server failed to start.\n\nPlease test the changes manually in the workspace directory: {self.git_manager.workspace_path}"
                self.jira_manager.add_comment(ticket.key, fallback_comment)
            
            # 10. Finalize and Report
            self.logger.info("Finalizing and updating Jira ticket")
            try:
                # Initialize commit_message with a default value in case no commit was made
                commit_message = f"feat({ticket.key}): {ticket.summary} (No new changes to commit)"
                if 'commit_message' in locals() and commit_message: # Check if a real commit message was set
                    pass # Keep the real one
                
                # We need to re-capture the commit message if it was created inside the try block
                if successful_operations or self._has_uncommitted_changes():
                    commit_message = f"feat({ticket.key}): {ticket.summary}"
                    if failed_operations:
                        commit_message += f" (partial - {len(failed_operations)} operations failed)"

                # Add completion summary if provided
                summary_section = ""
                if completion_summary:
                    summary_section = f"\n**Changes Summary:**\n{completion_summary}\n"

                completion_comment = f"""Automated implementation completed.

**Branch:** {feature_branch_name}
**Commit:** {commit_message}
**Local Server:** {server_url if server_url else 'Not available'}{summary_section}
Ready for review and testing."""
                
                self.jira_manager.add_comment(ticket.key, completion_comment)
                
                # Jira Status Transition Rules:
                # - "In Progress": Set when ticket is picked up (line 1835)
                # - "Resolved": Set on successful implementation completion
                # - "Pending": Set on failure/error (handled in handle_failure method)
                self.jira_manager.transition_ticket(ticket.key, "Resolved")
                
                self.logger.info(f"Successfully processed ticket {ticket.key}")
                
                # Keep server running if successfully started
                if self.server_manager and server_url:
                    self.logger.info(f"Local server will continue running at {server_url}")
                    self.logger.info("Press Ctrl+C to stop the server and exit")
                    
                    try:
                        # Keep the main thread alive while server runs
                        while True:
                            time.sleep(60)  # Check every minute
                            if not self.server_manager.server_thread.is_alive():
                                break
                    except KeyboardInterrupt:
                        self.logger.info("Received shutdown signal")
                        self.server_manager.stop_server()
                
            except Exception as e:
                self.logger.error(f"Failed to update Jira ticket status: {e}")
                # Don't mark as failed since the code changes were successful
        
        except KeyboardInterrupt:
            self.logger.info("Process interrupted by user")
            if self.server_manager:
                self.server_manager.stop_server()
        except Exception as e:
            self.logger.error(f"Unexpected error in orchestrator: {e}")
            if self.server_manager:
                self.server_manager.stop_server()
            sys.exit(1)


def main():
    """Entry point for the script"""
    # Clean temp artifacts BEFORE any logging to avoid file locks
    OrchestratorScript.clean_temp_artifacts_early()
    orchestrator = OrchestratorScript()
    orchestrator.run()


if __name__ == "__main__":
    main() 