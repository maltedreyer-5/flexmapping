/* SPDX-FileCopyrightText: 2026 Malte Dreyer */
/* SPDX-License-Identifier: MIT */
/**
 * Client-side Filtering für Kategorie-Seiten
 */

let categoryFilterInstance = null;

class CategoryFilter {
    constructor() {
        this.items = Array.from(document.querySelectorAll('.list-item'));
        this.institutionFilter = document.getElementById('institution-filter');
        this.sortFilter = document.getElementById('sort-filter');
        this.visibleCount = document.getElementById('visible-count');
        
        this.init();
    }
    
    init() {
        if (!this.items.length) {
            return;
        }
        
        // Event Listeners
        if (this.institutionFilter) {
            this.institutionFilter.addEventListener('change', () => this.applyFilters());
        }
        
        if (this.sortFilter) {
            this.sortFilter.addEventListener('change', () => this.applySort());
        }
        
        // Initial state
        this.updateCount();
    }
    
    setInstitutionFilter(institution) {
        if (this.institutionFilter) {
            // Finde die Option mit dem passenden Wert
            const options = Array.from(this.institutionFilter.options);
            const matchingOption = options.find(opt => opt.value === institution);
            
            if (matchingOption) {
                this.institutionFilter.value = institution;
            } else {
                // Falls exakter Match nicht gefunden, suche nach Teil-Match
                const partialMatch = options.find(opt => 
                    opt.value && (opt.value.includes(institution) || institution.includes(opt.value))
                );
                if (partialMatch) {
                    this.institutionFilter.value = partialMatch.value;
                }
            }
            
            this.applyFilters();
            
            // Scroll zum Filter und highlighten
            this.institutionFilter.scrollIntoView({ behavior: 'smooth', block: 'center' });
            this.institutionFilter.classList.add('filter-highlight');
            setTimeout(() => this.institutionFilter.classList.remove('filter-highlight'), 2000);
        }
    }
    
    applyFilters() {
        const selectedInstitution = this.institutionFilter.value;
        
        this.items.forEach(item => {
            const institution = item.dataset.institution;
            
            const institutionMatch = !selectedInstitution || institution === selectedInstitution;
            
            if (institutionMatch) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
        
        this.updateCount();
    }
    
    applySort() {
        const sortValue = this.sortFilter.value;
        const container = document.getElementById('content-list');
        
        if (!container) return;
        
        // Get visible items only
        const visibleItems = this.items.filter(item => item.style.display !== 'none');
        
        // Sort
        visibleItems.sort((a, b) => {
            if (sortValue === 'newest') {
                const dateA = new Date(a.dataset.date);
                const dateB = new Date(b.dataset.date);
                return dateB - dateA;
            } else if (sortValue === 'oldest') {
                const dateA = new Date(a.dataset.date);
                const dateB = new Date(b.dataset.date);
                return dateA - dateB;
            } else if (sortValue === 'title') {
                const titleA = a.dataset.title.toLowerCase();
                const titleB = b.dataset.title.toLowerCase();
                return titleA.localeCompare(titleB);
            }
            return 0;
        });
        
        // Re-append in new order
        visibleItems.forEach(item => container.appendChild(item));
    }
    
    updateCount() {
        const visible = this.items.filter(item => item.style.display !== 'none').length;
        
        if (this.visibleCount) {
            this.visibleCount.textContent = visible;
        }
    }
}

// Globale Funktion zum Filtern nach Institution (für onclick)
function filterByInstitution(institution) {
    if (categoryFilterInstance) {
        categoryFilterInstance.setInstitutionFilter(institution);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    categoryFilterInstance = new CategoryFilter();
});
