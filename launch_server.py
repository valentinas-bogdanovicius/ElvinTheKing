#!/usr/bin/env python3
"""
Standalone Development Server Launcher

This script launches a local HTTP server on port 777 to test the changes
made by the orchestrator script.

Usage:
    python launch_server.py [directory] [port]

Arguments:
    directory: Directory to serve (default: ./workspace)
    port: Port number (default: 777)

Author: AI Assistant
"""

import os
import sys
import socket
import threading
import time
import logging
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler


class ServerLauncher:
    """Handles local development server for testing changes"""
    
    def __init__(self, serve_directory: Path, port: int = 777):
        self.serve_directory = serve_directory
        self.port = port
        self.server = None
        self.server_thread = None
        self.setup_logging()
        self.logger = logging.getLogger(__name__)
    
    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
    
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
    
    def cleanup_port(self):
        """Kill any existing processes on the port"""
        self.logger.info(f"Cleaning up any existing processes on port {self.port}")
        os.system(f"netstat -ano | findstr :{self.port} > nul && (for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{self.port} ^| findstr LISTENING') do taskkill /f /pid %a 2>nul) || echo No processes found on port {self.port}")
        time.sleep(0.5)  # Wait for cleanup
    
    def start_server(self) -> str:
        """Start the local development server"""
        try:
            # Ensure directory exists and is accessible
            if not self.serve_directory.exists():
                raise Exception(f"Directory does not exist: {self.serve_directory}")
            
            # Store original directory to restore when server stops
            self.original_cwd = os.getcwd()
            
            # Clean up any existing processes on the port
            self.cleanup_port()
            
            # Find available port
            if not self.is_port_available():
                actual_port = self.find_available_port()
                self.logger.warning(f"Port {self.port} is busy, using port {actual_port}")
                self.port = actual_port
            
            # Change to serve directory and STAY there while server runs
            try:
                os.chdir(self.serve_directory)
                self.logger.info(f"Changed to serve directory: {self.serve_directory}")
                self.logger.info(f"Current working directory: {os.getcwd()}")
            except Exception as e:
                self.logger.error(f"Failed to change to serve directory: {e}")
                raise
            
            # Create server
            try:
                handler = SimpleHTTPRequestHandler
                self.server = HTTPServer(('localhost', self.port), handler)
                self.logger.info(f"Created HTTP server on localhost:{self.port}")
            except Exception as e:
                self.logger.error(f"Failed to create HTTP server: {e}")
                raise
            
            # Start server in a separate thread
            def run_server():
                try:
                    self.logger.info(f"Starting server thread on http://localhost:{self.port}")
                    self.server.serve_forever()
                except Exception as e:
                    self.logger.error(f"Server thread error: {e}")
            
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            
            # Give server time to start and verify it's running
            time.sleep(2)
            
            # Verify server is actually running
            if not self.server_thread.is_alive():
                raise Exception("Server thread failed to start")
            
            # Test if server is responding
            server_url = f"http://localhost:{self.port}"
            try:
                import urllib.request
                urllib.request.urlopen(server_url, timeout=5)
                self.logger.info(f"✅ Server verified and responding at {server_url}")
            except Exception as e:
                self.logger.warning(f"⚠️  Server may not be responding yet: {e}")
            
            # DO NOT restore original directory here - keep serving from the target directory
            
            self.logger.info(f"🚀 Local development server started successfully!")
            self.logger.info(f"📡 Server URL: {server_url}")
            self.logger.info(f"📁 Serving directory: {self.serve_directory.absolute()}")
            self.logger.info(f"🛑 Press Ctrl+C to stop the server")
            
            return server_url
            
        except Exception as e:
            self.logger.error(f"❌ Failed to start server: {e}")
            # Restore original directory if there was an error
            try:
                if hasattr(self, 'original_cwd'):
                    os.chdir(self.original_cwd)
            except:
                pass
            raise
    
    def stop_server(self):
        """Stop the local development server"""
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
                self.logger.info("🛑 Local development server stopped")
            except Exception as e:
                self.logger.error(f"Error stopping server: {e}")
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        
        # Restore original directory when server stops
        try:
            if hasattr(self, 'original_cwd'):
                os.chdir(self.original_cwd)
                self.logger.info(f"Restored original directory: {self.original_cwd}")
        except Exception as e:
            self.logger.warning(f"Failed to restore original directory: {e}")
    
    def run_until_interrupted(self):
        """Keep the server running until interrupted"""
        try:
            while True:
                if not self.server_thread.is_alive():
                    self.logger.error("❌ Server thread died unexpectedly")
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("\n🛑 Received shutdown signal")
            self.stop_server()


def main():
    """Entry point for the server launcher"""
    # Check for help flag
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help', 'help']:
        print("Standalone Development Server Launcher")
        print("=" * 40)
        print()
        print("This script launches a local HTTP server to test web applications.")
        print()
        print("Usage:")
        print("    python launch_server.py [directory] [port]")
        print()
        print("Arguments:")
        print("    directory: Directory to serve (default: ./workspace)")
        print("    port:      Port number (default: 777)")
        print()
        print("Examples:")
        print("    python launch_server.py                    # Serve ./workspace on port 777")
        print("    python launch_server.py workspace 8080     # Serve ./workspace on port 8080")
        print("    python launch_server.py . 3000             # Serve current directory on port 3000")
        print()
        print("Note: The server will automatically:")
        print("  - Kill any existing processes on the specified port")
        print("  - Find an alternative port if the specified one is busy")
        print("  - Try to open your default browser")
        print("  - Run until you press Ctrl+C")
        return
    
    # Parse command line arguments
    serve_directory = Path("./workspace")
    port = 777
    
    if len(sys.argv) > 1:
        serve_directory = Path(sys.argv[1])
    
    if len(sys.argv) > 2:
        try:
            port = int(sys.argv[2])
        except ValueError:
            print(f"Error: Invalid port number '{sys.argv[2]}'")
            print("Port must be a number between 1 and 65535")
            sys.exit(1)
    
    # Validate port range
    if not (1 <= port <= 65535):
        print(f"Error: Port {port} is out of valid range (1-65535)")
        sys.exit(1)
    
    # Validate directory
    if not serve_directory.exists():
        print(f"Error: Directory '{serve_directory}' does not exist")
        print(f"Available directories:")
        for item in Path(".").iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                print(f"  - {item}")
        print()
        print("Tip: Run 'python launch_server.py --help' for usage information")
        sys.exit(1)
    
    # Create and start server
    print(f"🚀 Starting development server...")
    print(f"📁 Directory: {serve_directory.absolute()}")
    print(f"🌐 Port: {port}")
    print()
    
    launcher = ServerLauncher(serve_directory, port)
    
    try:
        server_url = launcher.start_server()
        print(f"\n🎉 Server is ready! Open your browser to: {server_url}")
        print(f"📝 Files being served from: {serve_directory.absolute()}")
        
        # Try to open browser automatically
        try:
            import webbrowser
            webbrowser.open(server_url)
            print(f"🌐 Opened browser automatically")
        except:
            print(f"💡 Open your browser manually to: {server_url}")
        
        print()
        print("🔧 Server controls:")
        print("   - Press Ctrl+C to stop the server")
        print("   - Refresh your browser to see changes")
        print("   - Check the console for access logs")
        print()
        
        # Keep server running
        launcher.run_until_interrupted()
        
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 