# =============================================================================
# setup_project.py
# =============================================================================
# This script installs all required Python packages for the Silver Dolphins
# audit project. Run it once on any new computer before using main.py.
# =============================================================================

# HOW TO RUN IN SPYDER (v5 / Anaconda):
# ---------------------------------------
# 1. Open Spyder, then open this file via File > Open.
# 2. Confirm the working directory (bottom-right corner of Spyder) is set to
#    the ACG6415-Silver-Dolphins/ folder.
# 3. Press F5 or click the green Run button in the toolbar.
# 4. Watch the IPython console panel (bottom-right) for output.
#    You should see "Starting installation..." followed by pip output, then
#    "Installation complete!"

# HOW TO SET UP THE PROJECT ON A NEW COMPUTER:
# ----------------------------------------------
# 1. Install Python 3.x from https://www.python.org  (if not already installed)
# 2. Install Git from https://git-scm.com            (if not already installed)
# 3. Install Spyder — either via Anaconda (recommended) or `pip install spyder`
# 4. Clone the repository:
#       git clone <repository-url>
# 5. Open a terminal (or Spyder's IPython console) and navigate to the project
#    folder:
#       cd ACG6415-Silver-Dolphins
# 6. Run this script to install all dependencies automatically:
#       python setup_project.py
#    (or press F5 inside Spyder after following the Spyder steps above)

import subprocess  # Lets us run shell commands (like pip) from inside Python
import sys         # Gives us the path to the current Python interpreter

def install_requirements():
    """
    Installs all packages listed in requirements.txt using the same Python
    interpreter that is currently running this script.

    Using sys.executable (instead of just calling 'pip') guarantees that
    packages are installed into the correct environment — whether that is a
    virtual environment, Anaconda environment, or the system Python.
    """
    print("Starting installation of required packages...")
    print(f"Using Python interpreter: {sys.executable}\n")

    try:
        # Run: <current-python> -m pip install -r requirements.txt
        # check_call() raises an exception automatically if pip exits with an error
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
        )
        print("\nInstallation complete! All required packages are now installed.")
        print("You can now open and run main.py.")

    except subprocess.CalledProcessError as error:
        # pip returned a non-zero exit code — something went wrong
        print(
            f"\nInstallation failed (pip exited with code {error.returncode}).\n"
            "Possible fixes:\n"
            "  - Make sure your working directory is set to ACG6415-Silver-Dolphins/\n"
            "  - Check that requirements.txt exists in that folder\n"
            "  - Check your internet connection\n"
            "  - Try running: pip install -r requirements.txt  in your terminal"
        )


# Only run install_requirements() when this file is executed directly.
# (This guard prevents the install from running if another script imports this
# module by accident.)
if __name__ == "__main__":
    install_requirements()
