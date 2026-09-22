# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Create All German Universities and HAW/FH with Extended Metadata

Creates entities for:
- All major German universities
- All major Universities of Applied Sciences (HAW/FH)

Usage:
    python scripts/create_all_german_universities.py [--url http://localhost:8000]
"""
import argparse
import sys
from typing import List, Dict

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found. Install it with: pip install requests")
    sys.exit(1)

# ANSI Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'


def print_success(msg: str):
    print(f"{GREEN}✓{RESET} {msg}")


def print_error(msg: str):
    print(f"{RED}✗{RESET} {msg}")


def print_info(msg: str):
    print(f"{YELLOW}ℹ{RESET} {msg}")


def print_step(msg: str):
    print(f"{BLUE}→{RESET} {msg}")


def get_universities() -> List[Dict]:
    """
    Get all major German universities with extended metadata

    Includes:
    - TU9 universities
    - Excellence universities
    - Major regional universities
    """
    return [
        # === BERLIN ===
        {
            "canonical_name": "Technische Universität Berlin",
            "metadata": {
                "long_name": "Technische Universität Berlin",
                "short_name": "TU Berlin",
                "domain": "tu.berlin",
                "coordinates": [52.5125, 13.3269],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1879,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": True
            },
            "variants": ["TU Berlin", "TUB", "TU-Berlin", "Technische Uni Berlin"]
        },
        {
            "canonical_name": "Humboldt-Universität zu Berlin",
            "metadata": {
                "long_name": "Humboldt-Universität zu Berlin",
                "short_name": "HU Berlin",
                "domain": "hu-berlin.de",
                "coordinates": [52.5186, 13.3936],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1810,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["HU Berlin", "HU", "Humboldt-Uni", "Humboldt Universität"]
        },
        {
            "canonical_name": "Freie Universität Berlin",
            "metadata": {
                "long_name": "Freie Universität Berlin",
                "short_name": "FU Berlin",
                "domain": "fu-berlin.de",
                "coordinates": [52.4524, 13.2901],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1948,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["FU Berlin", "FU", "Freie Uni Berlin"]
        },

        # === BAYERN ===
        {
            "canonical_name": "Ludwig-Maximilians-Universität München",
            "metadata": {
                "long_name": "Ludwig-Maximilians-Universität München",
                "short_name": "LMU",
                "domain": "lmu.de",
                "coordinates": [48.1507, 11.5810],
                "city": "München",
                "state": "Bayern",
                "founded": 1472,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["LMU München", "LMU", "Uni München"]
        },
        {
            "canonical_name": "Technische Universität München",
            "metadata": {
                "long_name": "Technische Universität München",
                "short_name": "TUM",
                "domain": "tum.de",
                "coordinates": [48.1497, 11.5679],
                "city": "München",
                "state": "Bayern",
                "founded": 1868,
                "type": "Technische Universität",
                "excellence": True,
                "tu9": True
            },
            "variants": ["TUM", "TU München", "Technical University Munich"]
        },
        {
            "canonical_name": "Universität Regensburg",
            "metadata": {
                "long_name": "Universität Regensburg",
                "short_name": "Uni Regensburg",
                "domain": "uni-regensburg.de",
                "coordinates": [49.0447, 12.0963],
                "city": "Regensburg",
                "state": "Bayern",
                "founded": 1962,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UR", "Uni Regensburg"]
        },
        {
            "canonical_name": "Friedrich-Alexander-Universität Erlangen-Nürnberg",
            "metadata": {
                "long_name": "Friedrich-Alexander-Universität Erlangen-Nürnberg",
                "short_name": "FAU",
                "domain": "fau.de",
                "coordinates": [49.5967, 11.0045],
                "city": "Erlangen",
                "state": "Bayern",
                "founded": 1743,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["FAU", "Uni Erlangen-Nürnberg"]
        },
        {
            "canonical_name": "Universität Würzburg",
            "metadata": {
                "long_name": "Julius-Maximilians-Universität Würzburg",
                "short_name": "Uni Würzburg",
                "domain": "uni-wuerzburg.de",
                "coordinates": [49.7865, 9.9676],
                "city": "Würzburg",
                "state": "Bayern",
                "founded": 1402,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["JMU", "Uni Würzburg"]
        },
        {
            "canonical_name": "Universität Augsburg",
            "metadata": {
                "long_name": "Universität Augsburg",
                "short_name": "Uni Augsburg",
                "domain": "uni-augsburg.de",
                "coordinates": [48.3345, 10.9012],
                "city": "Augsburg",
                "state": "Bayern",
                "founded": 1970,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UniA", "Uni Augsburg"]
        },
        {
            "canonical_name": "Universität Bayreuth",
            "metadata": {
                "long_name": "Universität Bayreuth",
                "short_name": "Uni Bayreuth",
                "domain": "uni-bayreuth.de",
                "coordinates": [49.9299, 11.5892],
                "city": "Bayreuth",
                "state": "Bayern",
                "founded": 1975,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UBT", "Uni Bayreuth"]
        },
        {
            "canonical_name": "Universität Passau",
            "metadata": {
                "long_name": "Universität Passau",
                "short_name": "Uni Passau",
                "domain": "uni-passau.de",
                "coordinates": [48.5665, 13.4512],
                "city": "Passau",
                "state": "Bayern",
                "founded": 1978,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Passau"]
        },

        # === BADEN-WÜRTTEMBERG ===
        {
            "canonical_name": "Ruprecht-Karls-Universität Heidelberg",
            "metadata": {
                "long_name": "Ruprecht-Karls-Universität Heidelberg",
                "short_name": "Uni Heidelberg",
                "domain": "uni-heidelberg.de",
                "coordinates": [49.4093, 8.6946],
                "city": "Heidelberg",
                "state": "Baden-Württemberg",
                "founded": 1386,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["Uni Heidelberg", "Heidelberg University"]
        },
        {
            "canonical_name": "Karlsruher Institut für Technologie",
            "metadata": {
                "long_name": "Karlsruher Institut für Technologie",
                "short_name": "KIT",
                "domain": "kit.edu",
                "coordinates": [49.0094, 8.4044],
                "city": "Karlsruhe",
                "state": "Baden-Württemberg",
                "founded": 1825,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": True
            },
            "variants": ["KIT", "Karlsruhe Institute of Technology"]
        },
        {
            "canonical_name": "Eberhard Karls Universität Tübingen",
            "metadata": {
                "long_name": "Eberhard Karls Universität Tübingen",
                "short_name": "Uni Tübingen",
                "domain": "uni-tuebingen.de",
                "coordinates": [48.5216, 9.0576],
                "city": "Tübingen",
                "state": "Baden-Württemberg",
                "founded": 1477,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["Uni Tübingen", "University of Tübingen"]
        },
        {
            "canonical_name": "Universität Stuttgart",
            "metadata": {
                "long_name": "Universität Stuttgart",
                "short_name": "Uni Stuttgart",
                "domain": "uni-stuttgart.de",
                "coordinates": [48.7450, 9.1059],
                "city": "Stuttgart",
                "state": "Baden-Württemberg",
                "founded": 1829,
                "type": "Universität",
                "excellence": True,
                "tu9": True
            },
            "variants": ["Uni Stuttgart", "University of Stuttgart"]
        },
        {
            "canonical_name": "Universität Freiburg",
            "metadata": {
                "long_name": "Albert-Ludwigs-Universität Freiburg",
                "short_name": "Uni Freiburg",
                "domain": "uni-freiburg.de",
                "coordinates": [47.9935, 7.8461],
                "city": "Freiburg im Breisgau",
                "state": "Baden-Württemberg",
                "founded": 1457,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["Uni Freiburg", "ALU"]
        },
        {
            "canonical_name": "Universität Konstanz",
            "metadata": {
                "long_name": "Universität Konstanz",
                "short_name": "Uni Konstanz",
                "domain": "uni-konstanz.de",
                "coordinates": [47.6967, 9.1782],
                "city": "Konstanz",
                "state": "Baden-Württemberg",
                "founded": 1966,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["Uni Konstanz"]
        },
        {
            "canonical_name": "Universität Mannheim",
            "metadata": {
                "long_name": "Universität Mannheim",
                "short_name": "Uni Mannheim",
                "domain": "uni-mannheim.de",
                "coordinates": [49.4823, 8.4642],
                "city": "Mannheim",
                "state": "Baden-Württemberg",
                "founded": 1907,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UMA", "Uni Mannheim"]
        },
        {
            "canonical_name": "Universität Ulm",
            "metadata": {
                "long_name": "Universität Ulm",
                "short_name": "Uni Ulm",
                "domain": "uni-ulm.de",
                "coordinates": [48.4224, 9.9573],
                "city": "Ulm",
                "state": "Baden-Württemberg",
                "founded": 1967,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Ulm"]
        },
        {
            "canonical_name": "Universität Hohenheim",
            "metadata": {
                "long_name": "Universität Hohenheim",
                "short_name": "Uni Hohenheim",
                "domain": "uni-hohenheim.de",
                "coordinates": [48.7093, 9.2127],
                "city": "Stuttgart",
                "state": "Baden-Württemberg",
                "founded": 1818,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Hohenheim"]
        },

        # === NORDRHEIN-WESTFALEN ===
        {
            "canonical_name": "Rheinisch-Westfälische Technische Hochschule Aachen",
            "metadata": {
                "long_name": "Rheinisch-Westfälische Technische Hochschule Aachen",
                "short_name": "RWTH Aachen",
                "domain": "rwth-aachen.de",
                "coordinates": [50.7802, 6.0781],
                "city": "Aachen",
                "state": "Nordrhein-Westfalen",
                "founded": 1870,
                "type": "Technische Hochschule",
                "excellence": True,
                "tu9": True
            },
            "variants": ["RWTH Aachen", "RWTH", "TH Aachen", "RWTH Aachen University"]
        },
        {
            "canonical_name": "Universität zu Köln",
            "metadata": {
                "long_name": "Universität zu Köln",
                "short_name": "Uni Köln",
                "domain": "uni-koeln.de",
                "coordinates": [50.9282, 6.9282],
                "city": "Köln",
                "state": "Nordrhein-Westfalen",
                "founded": 1388,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["Uni Köln", "University of Cologne"]
        },
        {
            "canonical_name": "Westfälische Wilhelms-Universität Münster",
            "metadata": {
                "long_name": "Westfälische Wilhelms-Universität Münster",
                "short_name": "WWU Münster",
                "domain": "uni-muenster.de",
                "coordinates": [51.9633, 7.6124],
                "city": "Münster",
                "state": "Nordrhein-Westfalen",
                "founded": 1780,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["WWU Münster", "WWU", "Uni Münster"]
        },
        {
            "canonical_name": "Universität Bonn",
            "metadata": {
                "long_name": "Rheinische Friedrich-Wilhelms-Universität Bonn",
                "short_name": "Uni Bonn",
                "domain": "uni-bonn.de",
                "coordinates": [50.7278, 7.0851],
                "city": "Bonn",
                "state": "Nordrhein-Westfalen",
                "founded": 1818,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["Uni Bonn", "University of Bonn"]
        },
        {
            "canonical_name": "Technische Universität Dortmund",
            "metadata": {
                "long_name": "Technische Universität Dortmund",
                "short_name": "TU Dortmund",
                "domain": "tu-dortmund.de",
                "coordinates": [51.4926, 7.4129],
                "city": "Dortmund",
                "state": "Nordrhein-Westfalen",
                "founded": 1968,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["TU Dortmund", "TUD"]
        },
        {
            "canonical_name": "Ruhr-Universität Bochum",
            "metadata": {
                "long_name": "Ruhr-Universität Bochum",
                "short_name": "RUB",
                "domain": "ruhr-uni-bochum.de",
                "coordinates": [51.4446, 7.2617],
                "city": "Bochum",
                "state": "Nordrhein-Westfalen",
                "founded": 1962,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["RUB", "Uni Bochum"]
        },
        {
            "canonical_name": "Heinrich-Heine-Universität Düsseldorf",
            "metadata": {
                "long_name": "Heinrich-Heine-Universität Düsseldorf",
                "short_name": "HHU",
                "domain": "hhu.de",
                "coordinates": [51.1905, 6.7947],
                "city": "Düsseldorf",
                "state": "Nordrhein-Westfalen",
                "founded": 1965,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["HHU", "Uni Düsseldorf"]
        },
        {
            "canonical_name": "Universität Duisburg-Essen",
            "metadata": {
                "long_name": "Universität Duisburg-Essen",
                "short_name": "UDE",
                "domain": "uni-due.de",
                "coordinates": [51.4656, 7.0128],
                "city": "Essen",
                "state": "Nordrhein-Westfalen",
                "founded": 2003,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UDE", "Uni Duisburg-Essen"]
        },
        {
            "canonical_name": "Universität Bielefeld",
            "metadata": {
                "long_name": "Universität Bielefeld",
                "short_name": "Uni Bielefeld",
                "domain": "uni-bielefeld.de",
                "coordinates": [52.0387, 8.4937],
                "city": "Bielefeld",
                "state": "Nordrhein-Westfalen",
                "founded": 1969,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Bielefeld"]
        },
        {
            "canonical_name": "Universität Paderborn",
            "metadata": {
                "long_name": "Universität Paderborn",
                "short_name": "UPB",
                "domain": "uni-paderborn.de",
                "coordinates": [51.7069, 8.7737],
                "city": "Paderborn",
                "state": "Nordrhein-Westfalen",
                "founded": 1972,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UPB", "Uni Paderborn"]
        },
        {
            "canonical_name": "Bergische Universität Wuppertal",
            "metadata": {
                "long_name": "Bergische Universität Wuppertal",
                "short_name": "BUW",
                "domain": "uni-wuppertal.de",
                "coordinates": [51.2456, 7.1497],
                "city": "Wuppertal",
                "state": "Nordrhein-Westfalen",
                "founded": 1972,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["BUW", "Uni Wuppertal"]
        },
        {
            "canonical_name": "Universität Siegen",
            "metadata": {
                "long_name": "Universität Siegen",
                "short_name": "Uni Siegen",
                "domain": "uni-siegen.de",
                "coordinates": [50.9072, 8.0722],
                "city": "Siegen",
                "state": "Nordrhein-Westfalen",
                "founded": 1972,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Siegen"]
        },

        # === HESSEN ===
        {
            "canonical_name": "Johann Wolfgang Goethe-Universität Frankfurt am Main",
            "metadata": {
                "long_name": "Johann Wolfgang Goethe-Universität Frankfurt am Main",
                "short_name": "Goethe-Uni",
                "domain": "uni-frankfurt.de",
                "coordinates": [50.1280, 8.6648],
                "city": "Frankfurt am Main",
                "state": "Hessen",
                "founded": 1914,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Goethe-Uni", "Uni Frankfurt"]
        },
        {
            "canonical_name": "Technische Universität Darmstadt",
            "metadata": {
                "long_name": "Technische Universität Darmstadt",
                "short_name": "TU Darmstadt",
                "domain": "tu-darmstadt.de",
                "coordinates": [49.8775, 8.6548],
                "city": "Darmstadt",
                "state": "Hessen",
                "founded": 1877,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": True
            },
            "variants": ["TU Darmstadt", "TUD"]
        },
        {
            "canonical_name": "Philipps-Universität Marburg",
            "metadata": {
                "long_name": "Philipps-Universität Marburg",
                "short_name": "Uni Marburg",
                "domain": "uni-marburg.de",
                "coordinates": [50.8097, 8.7737],
                "city": "Marburg",
                "state": "Hessen",
                "founded": 1527,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Marburg"]
        },
        {
            "canonical_name": "Justus-Liebig-Universität Gießen",
            "metadata": {
                "long_name": "Justus-Liebig-Universität Gießen",
                "short_name": "JLU",
                "domain": "uni-giessen.de",
                "coordinates": [50.5847, 8.6743],
                "city": "Gießen",
                "state": "Hessen",
                "founded": 1607,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["JLU", "Uni Gießen"]
        },
        {
            "canonical_name": "Universität Kassel",
            "metadata": {
                "long_name": "Universität Kassel",
                "short_name": "Uni Kassel",
                "domain": "uni-kassel.de",
                "coordinates": [51.3127, 9.4797],
                "city": "Kassel",
                "state": "Hessen",
                "founded": 1971,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Kassel"]
        },

        # === NIEDERSACHSEN ===
        {
            "canonical_name": "Georg-August-Universität Göttingen",
            "metadata": {
                "long_name": "Georg-August-Universität Göttingen",
                "short_name": "Uni Göttingen",
                "domain": "uni-goettingen.de",
                "coordinates": [51.5414, 9.9355],
                "city": "Göttingen",
                "state": "Niedersachsen",
                "founded": 1737,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Göttingen"]
        },
        {
            "canonical_name": "Leibniz Universität Hannover",
            "metadata": {
                "long_name": "Leibniz Universität Hannover",
                "short_name": "LUH",
                "domain": "uni-hannover.de",
                "coordinates": [52.3813, 9.7202],
                "city": "Hannover",
                "state": "Niedersachsen",
                "founded": 1831,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": True
            },
            "variants": ["LUH", "Uni Hannover"]
        },
        {
            "canonical_name": "Technische Universität Braunschweig",
            "metadata": {
                "long_name": "Technische Universität Braunschweig",
                "short_name": "TU Braunschweig",
                "domain": "tu-braunschweig.de",
                "coordinates": [52.2741, 10.5237],
                "city": "Braunschweig",
                "state": "Niedersachsen",
                "founded": 1745,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": True
            },
            "variants": ["TU BS", "TU Braunschweig"]
        },
        {
            "canonical_name": "Carl von Ossietzky Universität Oldenburg",
            "metadata": {
                "long_name": "Carl von Ossietzky Universität Oldenburg",
                "short_name": "Uni Oldenburg",
                "domain": "uni-oldenburg.de",
                "coordinates": [53.1450, 8.1622],
                "city": "Oldenburg",
                "state": "Niedersachsen",
                "founded": 1973,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Oldenburg"]
        },
        {
            "canonical_name": "Universität Osnabrück",
            "metadata": {
                "long_name": "Universität Osnabrück",
                "short_name": "Uni Osnabrück",
                "domain": "uni-osnabrueck.de",
                "coordinates": [52.2820, 8.0223],
                "city": "Osnabrück",
                "state": "Niedersachsen",
                "founded": 1974,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Osnabrück", "UOS"]
        },

        # === HAMBURG / BREMEN ===
        {
            "canonical_name": "Universität Hamburg",
            "metadata": {
                "long_name": "Universität Hamburg",
                "short_name": "UHH",
                "domain": "uni-hamburg.de",
                "coordinates": [53.5672, 9.9867],
                "city": "Hamburg",
                "state": "Hamburg",
                "founded": 1919,
                "type": "Universität",
                "excellence": True,
                "tu9": False
            },
            "variants": ["UHH", "Uni Hamburg"]
        },
        {
            "canonical_name": "Technische Universität Hamburg",
            "metadata": {
                "long_name": "Technische Universität Hamburg",
                "short_name": "TUHH",
                "domain": "tuhh.de",
                "coordinates": [53.4604, 9.9690],
                "city": "Hamburg",
                "state": "Hamburg",
                "founded": 1978,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["TUHH", "TU Hamburg"]
        },
        {
            "canonical_name": "Universität Bremen",
            "metadata": {
                "long_name": "Universität Bremen",
                "short_name": "Uni Bremen",
                "domain": "uni-bremen.de",
                "coordinates": [53.1067, 8.8520],
                "city": "Bremen",
                "state": "Bremen",
                "founded": 1971,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Bremen"]
        },

        # === SACHSEN ===
        {
            "canonical_name": "Technische Universität Dresden",
            "metadata": {
                "long_name": "Technische Universität Dresden",
                "short_name": "TU Dresden",
                "domain": "tu-dresden.de",
                "coordinates": [51.0279, 13.7253],
                "city": "Dresden",
                "state": "Sachsen",
                "founded": 1828,
                "type": "Technische Universität",
                "excellence": True,
                "tu9": True
            },
            "variants": ["TUD", "TU Dresden"]
        },
        {
            "canonical_name": "Universität Leipzig",
            "metadata": {
                "long_name": "Universität Leipzig",
                "short_name": "Uni Leipzig",
                "domain": "uni-leipzig.de",
                "coordinates": [51.3397, 12.3731],
                "city": "Leipzig",
                "state": "Sachsen",
                "founded": 1409,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Leipzig"]
        },
        {
            "canonical_name": "Technische Universität Chemnitz",
            "metadata": {
                "long_name": "Technische Universität Chemnitz",
                "short_name": "TU Chemnitz",
                "domain": "tu-chemnitz.de",
                "coordinates": [50.8134, 12.9278],
                "city": "Chemnitz",
                "state": "Sachsen",
                "founded": 1836,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["TU Chemnitz", "TUC"]
        },

        # === WEITERE BUNDESLÄNDER ===
        {
            "canonical_name": "Christian-Albrechts-Universität zu Kiel",
            "metadata": {
                "long_name": "Christian-Albrechts-Universität zu Kiel",
                "short_name": "CAU",
                "domain": "uni-kiel.de",
                "coordinates": [54.3418, 10.1212],
                "city": "Kiel",
                "state": "Schleswig-Holstein",
                "founded": 1665,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["CAU", "Uni Kiel"]
        },
        {
            "canonical_name": "Johannes Gutenberg-Universität Mainz",
            "metadata": {
                "long_name": "Johannes Gutenberg-Universität Mainz",
                "short_name": "JGU",
                "domain": "uni-mainz.de",
                "coordinates": [49.9911, 8.2406],
                "city": "Mainz",
                "state": "Rheinland-Pfalz",
                "founded": 1477,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["JGU", "Uni Mainz"]
        },
        {
            "canonical_name": "Universität des Saarlandes",
            "metadata": {
                "long_name": "Universität des Saarlandes",
                "short_name": "UdS",
                "domain": "uni-saarland.de",
                "coordinates": [49.2547, 7.0410],
                "city": "Saarbrücken",
                "state": "Saarland",
                "founded": 1948,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UdS", "Uni Saarland"]
        },
        {
            "canonical_name": "Martin-Luther-Universität Halle-Wittenberg",
            "metadata": {
                "long_name": "Martin-Luther-Universität Halle-Wittenberg",
                "short_name": "MLU",
                "domain": "uni-halle.de",
                "coordinates": [51.4825, 11.9695],
                "city": "Halle (Saale)",
                "state": "Sachsen-Anhalt",
                "founded": 1502,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["MLU", "Uni Halle"]
        },
        {
            "canonical_name": "Otto-von-Guericke-Universität Magdeburg",
            "metadata": {
                "long_name": "Otto-von-Guericke-Universität Magdeburg",
                "short_name": "OVGU",
                "domain": "ovgu.de",
                "coordinates": [52.1389, 11.6442],
                "city": "Magdeburg",
                "state": "Sachsen-Anhalt",
                "founded": 1993,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["OVGU", "Uni Magdeburg"]
        },
        {
            "canonical_name": "Friedrich-Schiller-Universität Jena",
            "metadata": {
                "long_name": "Friedrich-Schiller-Universität Jena",
                "short_name": "FSU",
                "domain": "uni-jena.de",
                "coordinates": [50.9281, 11.5892],
                "city": "Jena",
                "state": "Thüringen",
                "founded": 1558,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["FSU", "Uni Jena"]
        },
        {
            "canonical_name": "Bauhaus-Universität Weimar",
            "metadata": {
                "long_name": "Bauhaus-Universität Weimar",
                "short_name": "Bauhaus-Uni",
                "domain": "uni-weimar.de",
                "coordinates": [50.9797, 11.3235],
                "city": "Weimar",
                "state": "Thüringen",
                "founded": 1860,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Bauhaus-Uni", "Uni Weimar"]
        },
        {
            "canonical_name": "Technische Universität Ilmenau",
            "metadata": {
                "long_name": "Technische Universität Ilmenau",
                "short_name": "TU Ilmenau",
                "domain": "tu-ilmenau.de",
                "coordinates": [50.6828, 10.9373],
                "city": "Ilmenau",
                "state": "Thüringen",
                "founded": 1894,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["TU Ilmenau"]
        },
        {
            "canonical_name": "Ernst-Moritz-Arndt-Universität Greifswald",
            "metadata": {
                "long_name": "Universität Greifswald",
                "short_name": "Uni Greifswald",
                "domain": "uni-greifswald.de",
                "coordinates": [54.0865, 13.3923],
                "city": "Greifswald",
                "state": "Mecklenburg-Vorpommern",
                "founded": 1456,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Greifswald"]
        },
        {
            "canonical_name": "Universität Rostock",
            "metadata": {
                "long_name": "Universität Rostock",
                "short_name": "Uni Rostock",
                "domain": "uni-rostock.de",
                "coordinates": [54.0787, 12.1043],
                "city": "Rostock",
                "state": "Mecklenburg-Vorpommern",
                "founded": 1419,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Rostock"]
        },

        # === BRANDENBURG ===
        {
            "canonical_name": "Universität Potsdam",
            "metadata": {
                "long_name": "Universität Potsdam",
                "short_name": "Uni Potsdam",
                "domain": "uni-potsdam.de",
                "coordinates": [52.3988, 13.1314],
                "city": "Potsdam",
                "state": "Brandenburg",
                "founded": 1991,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["UP", "Uni Potsdam"]
        },
        {
            "canonical_name": "Brandenburgische Technische Universität Cottbus-Senftenberg",
            "metadata": {
                "long_name": "Brandenburgische Technische Universität Cottbus-Senftenberg",
                "short_name": "BTU",
                "domain": "b-tu.de",
                "coordinates": [51.7606, 14.3336],
                "city": "Cottbus",
                "state": "Brandenburg",
                "founded": 1991,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["BTU", "BTU Cottbus-Senftenberg", "TU Cottbus"]
        },
        {
            "canonical_name": "Europa-Universität Viadrina Frankfurt (Oder)",
            "metadata": {
                "long_name": "Europa-Universität Viadrina Frankfurt (Oder)",
                "short_name": "Viadrina",
                "domain": "europa-uni.de",
                "coordinates": [52.3418, 14.5506],
                "city": "Frankfurt (Oder)",
                "state": "Brandenburg",
                "founded": 1991,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Viadrina", "Uni Viadrina", "Europa-Uni"]
        },

        # === RHEINLAND-PFALZ ===
        {
            "canonical_name": "Rheinland-Pfälzische Technische Universität Kaiserslautern-Landau",
            "metadata": {
                "long_name": "Rheinland-Pfälzische Technische Universität Kaiserslautern-Landau",
                "short_name": "RPTU",
                "domain": "rptu.de",
                "coordinates": [49.4247, 7.7559],
                "city": "Kaiserslautern",
                "state": "Rheinland-Pfalz",
                "founded": 2023,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["RPTU", "TU Kaiserslautern", "Uni Landau", "TUK"]
        },
        {
            "canonical_name": "Universität Trier",
            "metadata": {
                "long_name": "Universität Trier",
                "short_name": "Uni Trier",
                "domain": "uni-trier.de",
                "coordinates": [49.7490, 6.6371],
                "city": "Trier",
                "state": "Rheinland-Pfalz",
                "founded": 1473,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Trier"]
        },
        {
            "canonical_name": "Universität Koblenz",
            "metadata": {
                "long_name": "Universität Koblenz",
                "short_name": "Uni Koblenz",
                "domain": "uni-koblenz.de",
                "coordinates": [50.3569, 7.5890],
                "city": "Koblenz",
                "state": "Rheinland-Pfalz",
                "founded": 1990,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Koblenz"]
        },

        # === WEITERE BUNDESLÄNDER ===
        {
            "canonical_name": "Universität Erfurt",
            "metadata": {
                "long_name": "Universität Erfurt",
                "short_name": "Uni Erfurt",
                "domain": "uni-erfurt.de",
                "coordinates": [50.9773, 11.0345],
                "city": "Erfurt",
                "state": "Thüringen",
                "founded": 1379,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Erfurt"]
        },
        {
            "canonical_name": "TU Bergakademie Freiberg",
            "metadata": {
                "long_name": "Technische Universität Bergakademie Freiberg",
                "short_name": "TU Freiberg",
                "domain": "tu-freiberg.de",
                "coordinates": [50.9117, 13.3425],
                "city": "Freiberg",
                "state": "Sachsen",
                "founded": 1765,
                "type": "Technische Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["TU Freiberg", "Bergakademie Freiberg", "TUBAF"]
        },
        {
            "canonical_name": "Universität zu Lübeck",
            "metadata": {
                "long_name": "Universität zu Lübeck",
                "short_name": "Uni Lübeck",
                "domain": "uni-luebeck.de",
                "coordinates": [53.8699, 10.6866],
                "city": "Lübeck",
                "state": "Schleswig-Holstein",
                "founded": 1964,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Lübeck"]
        },
        {
            "canonical_name": "Europa-Universität Flensburg",
            "metadata": {
                "long_name": "Europa-Universität Flensburg",
                "short_name": "EUF",
                "domain": "uni-flensburg.de",
                "coordinates": [54.7833, 9.4333],
                "city": "Flensburg",
                "state": "Schleswig-Holstein",
                "founded": 1994,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["EUF", "Uni Flensburg"]
        },
        {
            "canonical_name": "Stiftung Universität Hildesheim",
            "metadata": {
                "long_name": "Stiftung Universität Hildesheim",
                "short_name": "Uni Hildesheim",
                "domain": "uni-hildesheim.de",
                "coordinates": [52.1500, 9.9500],
                "city": "Hildesheim",
                "state": "Niedersachsen",
                "founded": 1978,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Hildesheim"]
        },
        {
            "canonical_name": "Leuphana Universität Lüneburg",
            "metadata": {
                "long_name": "Leuphana Universität Lüneburg",
                "short_name": "Leuphana",
                "domain": "leuphana.de",
                "coordinates": [53.2500, 10.4000],
                "city": "Lüneburg",
                "state": "Niedersachsen",
                "founded": 1946,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Leuphana", "Uni Lüneburg"]
        },
        {
            "canonical_name": "Universität Vechta",
            "metadata": {
                "long_name": "Universität Vechta",
                "short_name": "Uni Vechta",
                "domain": "uni-vechta.de",
                "coordinates": [52.7333, 8.2833],
                "city": "Vechta",
                "state": "Niedersachsen",
                "founded": 1995,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["Uni Vechta"]
        },
        {
            "canonical_name": "Medizinische Hochschule Hannover",
            "metadata": {
                "long_name": "Medizinische Hochschule Hannover",
                "short_name": "MHH",
                "domain": "mh-hannover.de",
                "coordinates": [52.3874, 9.7234],
                "city": "Hannover",
                "state": "Niedersachsen",
                "founded": 1961,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["MHH", "Med Hochschule Hannover"]
        },
        {
            "canonical_name": "Stiftung Tierärztliche Hochschule Hannover",
            "metadata": {
                "long_name": "Stiftung Tierärztliche Hochschule Hannover",
                "short_name": "TiHo",
                "domain": "tiho-hannover.de",
                "coordinates": [52.3759, 9.8050],
                "city": "Hannover",
                "state": "Niedersachsen",
                "founded": 1778,
                "type": "Universität",
                "excellence": False,
                "tu9": False
            },
            "variants": ["TiHo", "Tierärztliche Hochschule Hannover"]
        },

        ]


def get_universities_of_applied_sciences() -> List[Dict]:
    """
    Get major German Universities of Applied Sciences (HAW/FH)
    """
    return [
        # === Größte HAW/FH ===
        {
            "canonical_name": "Technische Hochschule Köln",
            "metadata": {
                "long_name": "Technische Hochschule Köln",
                "short_name": "TH Köln",
                "domain": "th-koeln.de",
                "coordinates": [50.9422, 6.9560],
                "city": "Köln",
                "state": "Nordrhein-Westfalen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 24000
            },
            "variants": ["TH Köln", "FH Köln"]
        },
        {
            "canonical_name": "Hochschule München",
            "metadata": {
                "long_name": "Hochschule für angewandte Wissenschaften München",
                "short_name": "HM",
                "domain": "hm.edu",
                "coordinates": [48.1547, 11.5678],
                "city": "München",
                "state": "Bayern",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 18000
            },
            "variants": ["HM", "FH München"]
        },
        {
            "canonical_name": "Frankfurt University of Applied Sciences",
            "metadata": {
                "long_name": "Frankfurt University of Applied Sciences",
                "short_name": "Frankfurt UAS",
                "domain": "frankfurt-university.de",
                "coordinates": [50.1219, 8.6690],
                "city": "Frankfurt am Main",
                "state": "Hessen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 15000
            },
            "variants": ["Frankfurt UAS", "FH Frankfurt"]
        },
        {
            "canonical_name": "Hochschule für angewandte Wissenschaften Hamburg",
            "metadata": {
                "long_name": "Hochschule für angewandte Wissenschaften Hamburg",
                "short_name": "HAW Hamburg",
                "domain": "haw-hamburg.de",
                "coordinates": [53.5556, 10.0303],
                "city": "Hamburg",
                "state": "Hamburg",
                "founded": 1970,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 17000
            },
            "variants": ["HAW Hamburg", "FH Hamburg"]
        },
        {
            "canonical_name": "Hochschule Darmstadt",
            "metadata": {
                "long_name": "Hochschule Darmstadt",
                "short_name": "h_da",
                "domain": "h-da.de",
                "coordinates": [49.8667, 8.6333],
                "city": "Darmstadt",
                "state": "Hessen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 16000
            },
            "variants": ["h_da", "FH Darmstadt"]
        },
        {
            "canonical_name": "Ostfalia Hochschule für angewandte Wissenschaften",
            "metadata": {
                "long_name": "Ostfalia Hochschule für angewandte Wissenschaften",
                "short_name": "Ostfalia",
                "domain": "ostfalia.de",
                "coordinates": [52.2699, 10.5267],
                "city": "Wolfenbüttel",
                "state": "Niedersachsen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 13000
            },
            "variants": ["Ostfalia", "FH Braunschweig/Wolfenbüttel"]
        },
        {
            "canonical_name": "Hochschule für Technik und Wirtschaft Berlin",
            "metadata": {
                "long_name": "Hochschule für Technik und Wirtschaft Berlin",
                "short_name": "HTW Berlin",
                "domain": "htw-berlin.de",
                "coordinates": [52.4566, 13.5264],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1994,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 14000
            },
            "variants": ["HTW Berlin", "FH HTW"]
        },
        {
            "canonical_name": "Hochschule Karlsruhe",
            "metadata": {
                "long_name": "Hochschule Karlsruhe – Technik und Wirtschaft",
                "short_name": "HKA",
                "domain": "h-ka.de",
                "coordinates": [49.0145, 8.4043],
                "city": "Karlsruhe",
                "state": "Baden-Württemberg",
                "founded": 1878,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 8000
            },
            "variants": ["HKA", "Hochschule Karlsruhe", "FH Karlsruhe"]
        },
        {
            "canonical_name": "Technische Hochschule Nürnberg Georg Simon Ohm",
            "metadata": {
                "long_name": "Technische Hochschule Nürnberg Georg Simon Ohm",
                "short_name": "TH Nürnberg",
                "domain": "th-nuernberg.de",
                "coordinates": [49.4478, 11.0683],
                "city": "Nürnberg",
                "state": "Bayern",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 13000
            },
            "variants": ["TH Nürnberg", "Ohm-Hochschule"]
        },
        {
            "canonical_name": "Hochschule Hannover",
            "metadata": {
                "long_name": "Hochschule Hannover",
                "short_name": "HsH",
                "domain": "hs-hannover.de",
                "coordinates": [52.3759, 9.7320],
                "city": "Hannover",
                "state": "Niedersachsen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 10000
            },
            "variants": ["HsH", "FH Hannover"]
        },
        {
            "canonical_name": "Fachhochschule Dortmund",
            "metadata": {
                "long_name": "Fachhochschule Dortmund",
                "short_name": "FH Dortmund",
                "domain": "fh-dortmund.de",
                "coordinates": [51.4925, 7.4118],
                "city": "Dortmund",
                "state": "Nordrhein-Westfalen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 15000
            },
            "variants": ["FH Dortmund"]
        },
        {
            "canonical_name": "Hochschule für angewandte Wissenschaften Würzburg-Schweinfurt",
            "metadata": {
                "long_name": "Hochschule für angewandte Wissenschaften Würzburg-Schweinfurt",
                "short_name": "FHWS",
                "domain": "fhws.de",
                "coordinates": [49.7913, 9.9534],
                "city": "Würzburg",
                "state": "Bayern",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 9000
            },
            "variants": ["FHWS", "FH Würzburg"]
        },
        {
            "canonical_name": "Hochschule Osnabrück",
            "metadata": {
                "long_name": "Hochschule Osnabrück",
                "short_name": "HS Osnabrück",
                "domain": "hs-osnabrueck.de",
                "coordinates": [52.2845, 8.0471],
                "city": "Osnabrück",
                "state": "Niedersachsen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 13000
            },
            "variants": ["HS Osnabrück", "FH Osnabrück"]
        },
        {
            "canonical_name": "Hochschule Bremen",
            "metadata": {
                "long_name": "Hochschule Bremen",
                "short_name": "HSB",
                "domain": "hs-bremen.de",
                "coordinates": [53.0755, 8.8078],
                "city": "Bremen",
                "state": "Bremen",
                "founded": 1982,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 9000
            },
            "variants": ["HSB", "FH Bremen"]
        },
        {
            "canonical_name": "Hochschule Mannheim",
            "metadata": {
                "long_name": "Hochschule Mannheim",
                "short_name": "HS Mannheim",
                "domain": "hs-mannheim.de",
                "coordinates": [49.4742, 8.4673],
                "city": "Mannheim",
                "state": "Baden-Württemberg",
                "founded": 1898,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 5000
            },
            "variants": ["HS Mannheim", "FH Mannheim"]
        },
        {
            "canonical_name": "Hochschule Aachen",
            "metadata": {
                "long_name": "FH Aachen University of Applied Sciences",
                "short_name": "FH Aachen",
                "domain": "fh-aachen.de",
                "coordinates": [50.7794, 6.0654],
                "city": "Aachen",
                "state": "Nordrhein-Westfalen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 15000
            },
            "variants": ["FH Aachen"]
        },
        {
            "canonical_name": "Hochschule Augsburg",
            "metadata": {
                "long_name": "Hochschule für angewandte Wissenschaften Augsburg",
                "short_name": "HSA",
                "domain": "hs-augsburg.de",
                "coordinates": [48.3589, 10.9067],
                "city": "Augsburg",
                "state": "Bayern",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 7000
            },
            "variants": ["HSA", "FH Augsburg"]
        },
        {
            "canonical_name": "Hochschule Niederrhein",
            "metadata": {
                "long_name": "Hochschule Niederrhein",
                "short_name": "HSNR",
                "domain": "hs-niederrhein.de",
                "coordinates": [51.1913, 6.4390],
                "city": "Krefeld",
                "state": "Nordrhein-Westfalen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 14000
            },
            "variants": ["HSNR", "FH Niederrhein"]
        },
        {
            "canonical_name": "Hochschule Bonn-Rhein-Sieg",
            "metadata": {
                "long_name": "Hochschule Bonn-Rhein-Sieg",
                "short_name": "H-BRS",
                "domain": "h-brs.de",
                "coordinates": [50.7754, 7.1846],
                "city": "Sankt Augustin",
                "state": "Nordrhein-Westfalen",
                "founded": 1995,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 9000
            },
            "variants": ["H-BRS", "FH Bonn-Rhein-Sieg"]
        },
        {
            "canonical_name": "Hochschule Esslingen",
            "metadata": {
                "long_name": "Hochschule Esslingen",
                "short_name": "HE",
                "domain": "hs-esslingen.de",
                "coordinates": [48.7433, 9.3093],
                "city": "Esslingen am Neckar",
                "state": "Baden-Württemberg",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 6000
            },
            "variants": ["HE", "FH Esslingen"]
        },

        {
            "canonical_name": "Hochschule RheinMain",
            "metadata": {
                "long_name": "Hochschule RheinMain",
                "short_name": "HSRM",
                "domain": "hs-rm.de",
                "coordinates": [50.0021, 8.2472],
                "city": "Wiesbaden",
                "state": "Hessen",
                "founded": 1971,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 13000
            },
            "variants": ["HSRM", "HS RheinMain", "FH Wiesbaden"]
        },
        {
            "canonical_name": "Hochschule Anhalt",
            "metadata": {
                "long_name": "Hochschule Anhalt",
                "short_name": "HSA",
                "domain": "hs-anhalt.de",
                "coordinates": [51.8363, 12.2390],
                "city": "Köthen",
                "state": "Sachsen-Anhalt",
                "founded": 1991,
                "type": "Hochschule für angewandte Wissenschaften",
                "students": 7500
            },
            "variants": ["HSA", "FH Anhalt", "Hochschule Anhalt"]
        },

        ]


def create_entity(base_url: str, auth, entity_data: dict, entity_type: str = "university") -> tuple[bool, str]:
    """Create entity via API"""
    url = f"{base_url}/admin/entities"

    try:
        payload = {
            "entity_type": entity_type,
            "canonical_name": entity_data["canonical_name"],
            "metadata": entity_data["metadata"]
        }

        response = requests.post(url, json=payload, auth=auth)

        if response.status_code in [200, 201]:
            result = response.json()
            entity_id = result["id"]

            # Add variants
            variants_added = 0
            for variant in entity_data.get("variants", []):
                variant_url = f"{base_url}/admin/entities/{entity_id}/variants"
                variant_payload = {
                    "variant_name": variant,
                    "is_auto_detected": False
                }
                var_response = requests.post(variant_url, json=variant_payload, auth=auth)

                if var_response.status_code in [200, 201]:
                    variants_added += 1

            return True, f"ID {entity_id}, {variants_added} variants"

        elif response.status_code in (401, 403):
            return False, "the entity endpoints need an account with the admin role"

        elif response.status_code == 500 and "already exists" in response.text.lower():
            return True, "already exists"

        else:
            return False, f"Status {response.status_code}"

    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Create all German universities and HAW/FH")
    parser.add_argument("--user", help="account with the admin role")
    parser.add_argument("--password")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--universities-only",
        action="store_true",
        help="Only create universities, skip HAW/FH"
    )
    parser.add_argument(
        "--haw-only",
        action="store_true",
        help="Only create HAW/FH, skip universities"
    )
    args = parser.parse_args()

    if not args.user or not args.password:
        print_error("--user and --password are required: the entity endpoints "
                    "need an account with the admin role.")
        return 1
    auth = (args.user, args.password)

    base_url = args.url.rstrip("/")

    print("\n" + "=" * 70)
    print(f"{BOLD}  Create All German Universities{RESET}")
    print("=" * 70)
    print(f"  API URL: {base_url}")
    print("=" * 70 + "\n")

    # Check API
    print_step("Checking API connection...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code != 200:
            print_error(f"API returned status code {response.status_code}")
            return
        print_success("API is reachable\n")
    except Exception as e:
        print_error(f"Cannot connect to API: {str(e)}")
        return

    # Statistics
    created_unis = 0
    existing_unis = 0
    failed_unis = 0

    created_haw = 0
    existing_haw = 0
    failed_haw = 0

    # Create universities
    if not args.haw_only:
        print_step("Creating universities...")
        universities = get_universities()
        print_info(f"Loading {len(universities)} universities\n")

        for uni in universities:
            success, message = create_entity(base_url, auth, uni, "university")

            short_name = uni["metadata"]["short_name"]

            if success:
                if "already exists" in message:
                    print_info(f"{short_name:20} - Already exists")
                    existing_unis += 1
                else:
                    print_success(f"{short_name:20} - Created ({message})")
                    created_unis += 1
            else:
                print_error(f"{short_name:20} - Failed: {message}")
                failed_unis += 1

        print()

    # Create HAW/FH
    if not args.universities_only:
        print_step("Creating Universities of Applied Sciences (HAW/FH)...")
        haws = get_universities_of_applied_sciences()
        print_info(f"Loading {len(haws)} HAW/FH\n")

        for haw in haws:
            success, message = create_entity(base_url, auth, haw, "university")

            short_name = haw["metadata"]["short_name"]

            if success:
                if "already exists" in message:
                    print_info(f"{short_name:20} - Already exists")
                    existing_haw += 1
                else:
                    print_success(f"{short_name:20} - Created ({message})")
                    created_haw += 1
            else:
                print_error(f"{short_name:20} - Failed: {message}")
                failed_haw += 1

        print()

    # Summary
    total_universities = len(get_universities()) if not args.haw_only else 0
    total_haw = len(get_universities_of_applied_sciences()) if not args.universities_only else 0

    print("=" * 70)
    print(f"{BOLD}  SUMMARY{RESET}")
    print("=" * 70)

    if not args.haw_only:
        print(f"\n{BOLD}Universities:{RESET}")
        print(f"  Total:    {total_universities}")
        print(f"  Created:  {created_unis}")
        print(f"  Existing: {existing_unis}")
        print(f"  Failed:   {failed_unis}")

    if not args.universities_only:
        print(f"\n{BOLD}HAW/FH:{RESET}")
        print(f"  Total:    {total_haw}")
        print(f"  Created:  {created_haw}")
        print(f"  Existing: {existing_haw}")
        print(f"  Failed:   {failed_haw}")

    print("\n" + "=" * 70)

    total_failed = failed_unis + failed_haw

    if total_failed == 0:
        print_success("All entities processed successfully!")
        print()
        print(f"View entities: {base_url}/admin/entities")
    else:
        print_warning(f"{total_failed} entities failed. Check errors above.")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()