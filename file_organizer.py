import os
import shutil
import time
import logging
import configparser
from pathlib import Path
import shlex

def normalize_path(path_str):
    """Convert path string to normalized OS-specific format"""
    # Remove quotes if present
    path_str = path_str.strip('"\'')

    # Handle Windows-style paths when running on Unix-like systems
    if ':' in path_str:  # Windows path detected
        if os.name == 'nt':  # Running on Windows
            return str(Path(path_str).resolve())
        else:  # Running on Unix-like system (including WSL)
            # Convert Windows path to Unix path
            # First, split on colon and handle the drive letter
            drive, rest = path_str.split(':', 1)
            # Replace backslashes with forward slashes and ensure proper formatting
            rest = rest.replace('\\', '/').strip('/')
            return f"/mnt/{drive.lower()}/{rest}"
    
    # Handle Unix-style paths
    if path_str.startswith('/'):  # Unix absolute path
        if os.name == 'nt':  # Running on Windows
            # Convert Unix path to Windows path
            if path_str.startswith('/mnt/'):
                # Convert WSL path to Windows path
                drive = path_str[5:6].upper()
                path = path_str[6:].replace('/', '\\')
                return f"{drive}:{path}"
            else:
                # Just normalize the path for Windows
                return str(Path(path_str).resolve())
        else:  # Running on Unix-like system
            return str(Path(path_str).resolve())
    
    # If we get here, the path might not be absolute
    raise ValueError(f"Path must be absolute: {path_str}")

def normalize_paths(paths_str):
    """Convert comma-separated path string to list of normalized paths"""
    normalized = []
    # Split by comma while preserving quoted strings
    try:
        paths = shlex.split(paths_str)  # This handles quoted strings properly
        for p in paths:
            if ',' in p:  # Handle multiple paths in a quoted string
                for subpath in p.split(','):
                    if subpath.strip():
                        try:
                            normalized.append(normalize_path(subpath.strip()))
                        except ValueError as e:
                            print(f"Warning: {e}")
            elif p.strip():
                try:
                    normalized.append(normalize_path(p.strip()))
                except ValueError as e:
                    print(f"Warning: {e}")
    except ValueError as e:
        # Fall back to simple comma splitting if shlex fails
        for p in paths_str.split(','):
            if p.strip():
                try:
                    normalized.append(normalize_path(p.strip()))
                except ValueError as e:
                    print(f"Warning: {e}")
    return normalized

def load_config(config_file='file_organizer.config.ini'):
    """Load configuration from file, creating default if doesn't exist"""
    config = configparser.ConfigParser()
    
    if os.path.exists(config_file):
        config.read(config_file)
    else:
        config['Paths'] = {
            'search_paths': '',
            'storage_location': '',
            'extensions_file': ''
        }
        with open(config_file, 'w') as f:
            config.write(f)
    
    return config

def save_config(config, config_file='file_organizer.config.ini'):
    """Save configuration to file"""
    with open(config_file, 'w') as f:
        config.write(f)

def get_input_with_default(prompt, default=''):
    """Get user input with a default value"""
    if default:
        user_input = input(f"{prompt} (Press Enter for '{default}'): ")
        return user_input if user_input.strip() else default
    return input(prompt)

def organize_files_by_extension(search_paths, storage_location, extensions_file):
    """
    Recursively scans search paths for files with specified extensions,
    copies them to a storage location organized by extension, and logs the process.

    Args:
        search_paths: A list of paths to search.
        storage_location: The root directory to store the organized files.
        extensions_file: A file containing a list of file extensions to search for.
    """
    # Normalize all paths
    storage_location = normalize_path(storage_location)
    extensions_file = normalize_path(extensions_file)
    search_paths = [normalize_path(path) for path in search_paths]

    # Create a log file
    log_file = os.path.join(storage_location, "file_organization_log.txt")
    logging.basicConfig(filename=log_file, level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    # Load extensions from file
    extensions = {}
    try:
        with open(extensions_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and section headers
                if not line or line.startswith('#'):
                    continue
                
                # Remove comments in parentheses
                if '(' in line:
                    line = line.split('(')[0]
                
                # Handle multiple extensions separated by commas
                ext_list = [e.strip() for e in line.split(',')]
                
                # Process each extension
                for ext in ext_list:
                    # Ensure extension starts with a dot
                    ext = ext.strip().lower()
                    if not ext:  # Skip if empty after stripping
                        continue
                    if not ext.startswith('.'):
                        ext = '.' + ext
                    extensions[ext] = ""  # No description needed since they're comments
    except FileNotFoundError:
        logging.error(f"Error: Extensions file not found: {extensions_file}")
        print(f"Error: Extensions file not found: {extensions_file}")
        return

    # Dictionary to store file counts by extension
    file_counts = {}
    for ext in extensions:
        file_counts[ext] = 0

    # Dictionary to track which extension directories have been created
    created_dirs = set()

    # Start scanning and copying
    start_time = time.time()
    logging.info("Starting file organization process...")
    print("Starting file organization process...")

    for search_path in search_paths:
        for root, _, files in os.walk(search_path):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in extensions:
                    # Create extension directory only if we haven't yet and we found a file
                    if file_ext not in created_dirs:
                        ext_dir = os.path.join(storage_location, f"Extension-{file_ext}")
                        os.makedirs(ext_dir, exist_ok=True)
                        created_dirs.add(file_ext)

                    source_path = os.path.join(root, file)
                    destination_dir = os.path.join(storage_location, f"Extension-{file_ext}")
                    destination_path = os.path.join(destination_dir, file)

                    # Copy the file
                    try:
                        shutil.copy2(source_path, destination_path)  # copy2 preserves metadata
                        logging.info(f"Copied: {source_path} -> {destination_path} {extensions.get(file_ext,'')}")
                        print(f"Copied: {source_path} -> {destination_path} {extensions.get(file_ext,'')}")
                        file_counts[file_ext] += 1
                    except Exception as e:
                        logging.error(f"Error copying {source_path}: {e}")
                        print(f"Error copying {source_path}: {e}")

    end_time = time.time()
    elapsed_time = end_time - start_time

    # Log and display summary
    logging.info("File organization process completed.")
    logging.info(f"Total time taken: {elapsed_time:.2f} seconds")
    logging.info("Summary of file counts:")
    print("\nFile organization process completed.")
    print(f"Total time taken: {elapsed_time:.2f} seconds")
    print("Summary of file counts:")

    # Only show extensions where files were found
    for ext, count in file_counts.items():
        if count > 0:  # Only log extensions with files found
            logging.info(f"{ext}: {count} {extensions.get(ext,'')}")
            print(f"{ext}: {count} {extensions.get(ext,'')}")

if __name__ == "__main__":
    # Load saved configuration
    config = load_config()
    
    # Get user input with defaults from config
    default_search_paths = config.get('Paths', 'search_paths', fallback='')
    default_storage = config.get('Paths', 'storage_location', fallback='')
    default_extensions = config.get('Paths', 'extensions_file', fallback='')

    search_paths_input = get_input_with_default(
        "Enter search paths separated by commas",
        default_search_paths
    )
    storage_location = get_input_with_default(
        "Enter the storage location",
        default_storage
    )
    extensions_file = get_input_with_default(
        "Enter the path to the extensions file",
        default_extensions
    )

    # Normalize paths
    search_paths = normalize_paths(search_paths_input)
    storage_location = normalize_path(storage_location)
    extensions_file = normalize_path(extensions_file)

    # Validate paths
    valid = True
    for path in search_paths:
        if not os.path.isdir(path):
            print(f"Error: Invalid search path: {path}")
            valid = False
    
    if not os.path.isdir(storage_location):
        print(f"Error: Invalid storage location: {storage_location}")
        valid = False
    
    if not os.path.isfile(extensions_file):
        print(f"Error: Invalid extensions file: {extensions_file}")
        valid = False

    if not valid:
        exit(1)

    # Save the new configuration
    config['Paths'] = {
        'search_paths': search_paths_input,
        'storage_location': storage_location,
        'extensions_file': extensions_file
    }
    save_config(config)

    # Call the function to start the process
    organize_files_by_extension(search_paths, storage_location, extensions_file)