# AI-Driven Development Workflow Orchestrator

This Python script automates the process of translating Jira tickets into committed code changes using AI agents powered by Google's Gemini API or Anthropic's Claude API.

## Overview

The orchestrator script performs the following workflow:

1. **Fetch Task**: Retrieves the oldest open/reopened Jira ticket from a specified project
2. **Prepare Workspace**: Clones or updates the Git repository
3. **Invoke BA Agent**: Uses AI to analyze the ticket and generate a specification
4. **Invoke Coding Agent**: Uses AI to implement code changes based on the specification
5. **Apply Changes**: Creates a new Git branch, applies patches, commits, and pushes
6. **Update Jira**: Comments on the ticket and transitions it to "In Review"

## Prerequisites

- Python 3.8 or higher
- Git installed and configured
- Access to a Jira instance with API token
- AI API key (Google AI for Gemini or Anthropic for Claude)
- Git repository with appropriate access permissions

## Installation

1. Clone or download this repository
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. For Anthropic Claude support, install the additional package:
   ```bash
   pip install anthropic
   ```

## Configuration

1. Copy the example environment file:
   ```bash
   cp env.example .env
   ```

2. Edit the `.env` file with your configuration:

### Jira Configuration
- `JIRA_SERVER`: Your Jira instance URL (e.g., `https://yourcompany.atlassian.net`)
- `JIRA_USERNAME`: Your Jira username/email
- `JIRA_API_TOKEN`: Generate an API token from your Jira account settings
- `JIRA_PROJECT_KEY`: The project key to monitor for tickets (e.g., `HAB`)

### AI Provider Configuration

You can configure different AI providers for the Business Analyst and Coding agents, allowing you to optimize each agent with the most suitable model.

#### Option 1: Same Provider for Both Agents (Simple)
- `AI_PROVIDER`: Set to `gemini` or `anthropic` (applies to both agents)

#### Option 2: Different Providers for Each Agent (Advanced)
- `BA_AI_PROVIDER`: AI provider for Business Analyst agent (`gemini` or `anthropic`)
- `CODING_AI_PROVIDER`: AI provider for Coding agent (`gemini` or `anthropic`)

#### Google Gemini Configuration (if using any Gemini provider)
- `GEMINI_API_KEY`: Get your API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
- `GEMINI_MODEL`: Optional, defaults to `gemini-2.0-flash-exp`
- `BA_GEMINI_MODEL`: Optional, specific model for BA agent
- `CODING_GEMINI_MODEL`: Optional, specific model for Coding agent

#### Anthropic Claude Configuration (if using any Anthropic provider)
- `ANTHROPIC_API_KEY`: Get your API key from [Anthropic Console](https://console.anthropic.com/)
- `ANTHROPIC_MODEL`: Optional, defaults to `claude-3-5-sonnet-20241022`
- `BA_ANTHROPIC_MODEL`: Optional, specific model for BA agent  
- `CODING_ANTHROPIC_MODEL`: Optional, specific model for Coding agent

#### Example Configurations

**Same provider for both agents:**
```bash
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
```

**Different providers for each agent:**
```bash
BA_AI_PROVIDER=anthropic
CODING_AI_PROVIDER=gemini
ANTHROPIC_API_KEY=your-anthropic-key
GEMINI_API_KEY=your-gemini-key
```

**Different models for each agent:**
```bash
BA_AI_PROVIDER=anthropic
CODING_AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
BA_ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
CODING_ANTHROPIC_MODEL=claude-3-5-haiku-20241022
```

### Git Configuration
- `GIT_REPO_URL`: The HTTPS or SSH URL of your code repository
- `GIT_WORKSPACE_PATH`: Local directory path for the cloned repository (e.g., `./workspace`)

## Usage

Run the orchestrator script:

```bash
python process_jira_ticket.py
```

The script will:
- Look for the oldest open/reopened ticket in your Jira project
- Process it through the AI workflow
- Create a feature branch with the implemented changes
- Update the Jira ticket status

## Script Architecture

### Core Classes

- **ConfigManager**: Manages environment variable loading and validation
- **JiraManager**: Handles all Jira API operations (fetching tickets, comments, status transitions)
- **GitManager**: Manages Git operations (cloning, branching, patching, committing)
- **AIAgent**: Interfaces with Google's Gemini API for BA and Coding agents
- **OrchestratorScript**: Main coordinator class that orchestrates the entire workflow

### Error Handling

The script includes comprehensive error handling:
- Configuration validation on startup
- API error handling with proper logging
- Automatic Jira ticket updates on failures
- Git operation error recovery
- JSON parsing validation for AI responses

### Logging

The script logs all operations to:
- Console output (INFO level)
- `orchestrator.log` file (detailed logging)

## AI Agent Workflows

### Business Analyst Agent
Analyzes Jira tickets and produces a JSON specification containing:
- File paths to be modified
- Description of required changes
- Acceptance criteria
- Estimated complexity

### Coding Agent
Implements changes based on the BA specification and produces:
- Unified diff patches for each file
- Operation type (apply_diff)
- File path for each change

## Customization

### BA Agent Instructions
The BA Agent prompt template can be customized in the `AIAgent.invoke_ba_agent()` method to match your specific requirements and JSON schema.

### Coding Agent Instructions
The Coding Agent prompt can be modified in the `AIAgent.invoke_coding_agent()` method to adjust coding standards and output format.

### Git Workflow
The Git branch naming convention and commit message format can be customized in the `OrchestratorScript.run()` method.

## Security Considerations

- Store all credentials in the `.env` file, never commit them to version control
- Use API tokens instead of passwords for Jira authentication
- Ensure Git repository access is properly configured
- Consider running the script in a sandboxed environment

## Troubleshooting

### Common Issues

1. **Missing Environment Variables**: Ensure all required variables are set in `.env`
2. **Jira Authentication Errors**: Verify your API token and username
3. **Git Access Issues**: Check repository URL and authentication
4. **AI API Errors**: Verify Gemini API key and quota
5. **Patch Application Failures**: Review the generated patches for syntax issues

### Debug Mode

For detailed debugging, modify the logging level in `setup_logging()`:
```python
logging.basicConfig(level=logging.DEBUG, ...)
```

## Limitations

- Processes one ticket at a time
- Requires tickets to be in "Open" or "Reopened" status
- AI agents may require fine-tuning for specific codebases
- Patch application depends on file structure stability

## Contributing

To extend the orchestrator:

1. Follow the existing class structure and error handling patterns
2. Add comprehensive logging for new operations
3. Include proper exception handling
4. Update the README with new configuration options

## License

This script is provided as-is for automation purposes. Please ensure compliance with your organization's policies before use. 

## ⚡ Claude Prompt Caching

When using Anthropic Claude models, the system automatically leverages **prompt caching** to significantly improve performance and reduce costs:

### 🚀 **Performance Benefits**
- **Up to 90% cost reduction** for cached content
- **Up to 85% latency reduction** for long prompts
- **Automatic optimization** - no manual configuration required

### 🎯 **What Gets Cached**

**BA Agent Caching:**
- ✅ **Instructions** - Business analyst guidelines and formatting rules
- ✅ **Codebase Structure** - Complete project file structure and content
- 🔄 **Dynamic per ticket** - JIRA ticket details and attachments

**Coding Agent Caching:**
- ✅ **Instructions** - Coding guidelines and operation formats
- ✅ **BA Specification** - Business requirements (cached per ticket)
- ✅ **Project Structure** - File organization and patterns
- 🔄 **Dynamic per turn** - Conversation history and file requests

### 📊 **Cache Monitoring**

The system automatically logs cache performance metrics:
```
INFO - Anthropic ba agent - Cache write: 2048 tokens
INFO - Anthropic ba agent - Cache read: 2048 tokens  
INFO - Anthropic coding agent - Cache read: 1536 tokens
```

### ⚙️ **Technical Details**

- **Cache Lifetime**: 5 minutes (refreshed on each use)
- **Minimum Cache Size**: 1024 tokens (Sonnet/Opus), 2048 tokens (Haiku)
- **Automatic Fallback**: Uses regular prompts if content too small to cache
- **Beta API**: Uses `anthropic-beta: prompt-caching-2024-07-31` header 