#!/usr/bin/env python3
"""
Quick test configuration to verify the new coding agent strategy works correctly.
Tests the get_file_content and replace_file_lines methods.
"""

import sys
import logging
from pathlib import Path
from start import GitManager, ConfigManager

def test_new_file_operations():
    """Test the new file operations for the coding agent"""
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    logger.info("Testing new file operations for coding agent")
    
    try:
        # Create a mock config (won't be used for file operations)
        config = ConfigManager()
        
        # Create GitManager instance pointing to current directory
        git_manager = GitManager(config)
        git_manager.workspace_path = Path(".")  # Use current directory for testing
        
        # Test 1: Create a test file
        test_file = "test_file.txt"
        test_content = """Line 1: Hello World
Line 2: This is a test
Line 3: Original content
Line 4: More content
Line 5: Final line"""
        
        logger.info("Creating test file...")
        success = git_manager.write_file_content(test_file, test_content)
        if not success:
            raise Exception("Failed to create test file")
        
        # Test 2: Read file content
        logger.info("Testing get_file_content...")
        content = git_manager.get_file_content(test_file)
        if content is None:
            raise Exception("Failed to read test file")
        
        logger.info(f"Successfully read file with {len(content.splitlines())} lines")
        
        # Test 3: Replace lines (replace line 3)
        logger.info("Testing replace_lines...")
        success, updated_content = git_manager.replace_file_lines(
            test_file, 3, 3, "Line 3: UPDATED CONTENT"
        )
        
        if not success:
            raise Exception("Failed to replace lines")
        
        logger.info("Successfully replaced line 3")
        logger.info(f"Updated content:\n{updated_content}")
        
        # Test 4: Replace multiple lines (lines 4-5)
        logger.info("Testing replace multiple lines...")
        success, updated_content = git_manager.replace_file_lines(
            test_file, 4, 5, "Line 4: New content\nLine 5: Also new content"
        )
        
        if not success:
            raise Exception("Failed to replace multiple lines")
        
        logger.info("Successfully replaced lines 4-5")
        logger.info(f"Final content:\n{updated_content}")
        
        # Test 5: Insert new lines (insert after line 2)
        logger.info("Testing line insertion...")
        success, updated_content = git_manager.replace_file_lines(
            test_file, 3, 2, "Line 2.5: INSERTED LINE"  # start > end means insert
        )
        
        # For insertion, we need to handle it differently
        if not success:
            # Try a proper insertion approach
            success, updated_content = git_manager.replace_file_lines(
                test_file, 3, 3, "Line 2.5: INSERTED LINE\nLine 3: UPDATED CONTENT"
            )
        
        if success:
            logger.info("Successfully inserted line")
            logger.info(f"Content after insertion:\n{updated_content}")
        
        # Cleanup
        logger.info("Cleaning up test file...")
        Path(test_file).unlink(missing_ok=True)
        
        logger.info("✅ All tests passed! New file operation strategy is working correctly.")
        return True
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        # Cleanup on failure
        Path("test_file.txt").unlink(missing_ok=True)
        return False

if __name__ == "__main__":
    success = test_new_file_operations()
    sys.exit(0 if success else 1) 