"""
Albion Fame Tracker
Nécessite : Python 3.10+, npcap (https://npcap.com), scapy
Lancer en tant qu'Administrateur.
"""
import sys
import os

if sys.platform == "win32":
    # Assurer que les imports relatifs fonctionnent
    sys.path.insert(0, os.path.dirname(__file__))

from gui.app import AlbionTrackerApp

if __name__ == "__main__":
    app = AlbionTrackerApp()
    app.mainloop()
