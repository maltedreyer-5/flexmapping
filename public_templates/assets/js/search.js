/* SPDX-FileCopyrightText: 2026 Malte Dreyer */
/* SPDX-License-Identifier: MIT */
/**
 * Client-side search for the generated site
 * Lädt Search-Index und ermöglicht Volltext-Suche ohne Backend
 * FIXED: Dynamische URL-Pfade basierend auf window.URL_PREFIX
 * NEU: Entity-Autocomplete beim Tippen
 */

class Search {
    constructor() {
        this.index = [];
        this.entities = [];  // NEU: Entity-Index für Autocomplete
        this.currentResults = [];
        this.activeCategories = new Set();
        this.autocompleteVisible = false;
        this.selectedSuggestionIndex = -1;

        // FIXED: URL-Präfix aus globaler Variable oder automatisch ermitteln
        // Das Template setzt window.URL_PREFIX, falls nicht gesetzt -> automatisch ermitteln
        this.urlPrefix = this.detectUrlPrefix();

        // DOM Elements
        this.searchInput = document.getElementById('search-input');
        this.searchButton = document.getElementById('search-button');
        this.resultsHeader = document.getElementById('results-header');
        this.resultsCount = document.getElementById('results-count');
        this.searchQuery = document.getElementById('search-query');
        this.clearSearchBtn = document.getElementById('clear-search');
        this.loadingState = document.getElementById('loading-state');
        this.emptyState = document.getElementById('empty-state');
        this.noResultsState = document.getElementById('no-results-state');
        this.resultsList = document.getElementById('results-list');
        this.categoryFilters = document.querySelectorAll('.category-filter');

        this.init();
    }

    /**
     * Ermittelt den URL-Präfix automatisch basierend auf dem aktuellen Pfad
     * Falls die Seite unter /public/ läuft, wird '/public' als Präfix verwendet
     * Falls die Seite unter /en/ läuft, wird '/en' als Präfix verwendet
     * Falls die Seite unter / läuft, wird '' als Präfix verwendet
     */
    detectUrlPrefix() {
        // Prüfe zuerst ob ein globaler Präfix gesetzt wurde
        if (typeof window.URL_PREFIX !== 'undefined') {
            console.log('Using configured URL_PREFIX:', window.URL_PREFIX);
            return window.URL_PREFIX;
        }

        // Automatische Erkennung basierend auf aktuellem Pfad
        const currentPath = window.location.pathname;

        // Wenn wir unter /en/ sind, nutze /en als Präfix
        if (currentPath.startsWith('/en/') || currentPath === '/en') {
            console.log('Auto-detected URL prefix: /en');
            return '/en';
        }

        // Wenn wir unter /public/ sind, nutze /public als Präfix
        if (currentPath.startsWith('/public/') || currentPath === '/public') {
            console.log('Auto-detected URL prefix: /public');
            return '/public';
        }

        // Sonst kein Präfix (Root-Deployment)
        console.log('Auto-detected URL prefix: (empty - root deployment)');
        return '';
    }

    async init() {
        // Lade Search-Index und Entity-Index
        await this.loadIndex();
        await this.loadEntityIndex();
        
        // Autocomplete-Dropdown erstellen
        this.createAutocompleteDropdown();

        // Event Listeners
        this.searchButton.addEventListener('click', () => {
            this.hideAutocomplete();
            this.performSearch();
        });
        
        this.searchInput.addEventListener('keydown', (e) => {
            // Keyboard-Navigation für Autocomplete
            if (this.autocompleteVisible) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.navigateSuggestion(1);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.navigateSuggestion(-1);
                } else if (e.key === 'Enter') {
                    if (this.selectedSuggestionIndex >= 0) {
                        e.preventDefault();
                        this.selectSuggestion(this.selectedSuggestionIndex);
                    } else {
                        this.hideAutocomplete();
                        this.performSearch();
                    }
                } else if (e.key === 'Escape') {
                    this.hideAutocomplete();
                }
            } else if (e.key === 'Enter') {
                this.performSearch();
            }
        });

        // Live-Suche und Autocomplete bei Eingabe (mit Debounce)
        this.debounceTimer = null;
        this.autocompleteTimer = null;
        
        this.searchInput.addEventListener('input', () => {
            const query = this.searchInput.value.trim();
            
            // Autocomplete sofort aktualisieren (schneller als Suche)
            if (this.autocompleteTimer) {
                clearTimeout(this.autocompleteTimer);
            }
            this.autocompleteTimer = setTimeout(() => {
                if (query.length >= 2) {
                    this.showAutocomplete(query);
                } else {
                    this.hideAutocomplete();
                }
            }, 100);
            
            // Suche mit längerem Debounce
            if (this.debounceTimer) {
                clearTimeout(this.debounceTimer);
            }
            this.debounceTimer = setTimeout(() => {
                this.debounceTimer = null;
                this.performSearch();
            }, 300);
        });
        
        // Autocomplete bei Klick außerhalb schließen
        document.addEventListener('click', (e) => {
            if (!this.searchInput.contains(e.target) && !this.autocompleteDropdown.contains(e.target)) {
                this.hideAutocomplete();
            }
        });

        // Clear button
        if (this.clearSearchBtn) {
            this.clearSearchBtn.addEventListener('click', () => this.clearSearch());
        }

        // Category filters
        this.categoryFilters.forEach(filter => {
            this.activeCategories.add(filter.value);
            filter.addEventListener('change', () => this.updateFilters());
        });

        // Check URL parameter for initial search
        const urlParams = new URLSearchParams(window.location.search);
        const query = urlParams.get('q');
        if (query) {
            this.searchInput.value = query;
        }
        
        // Immer Suche ausführen (zeigt alle bei leerem Query)
        this.performSearch();
    }
    
    async loadEntityIndex() {
        try {
            const entityUrl = `${this.urlPrefix}/assets/data/entities.json`;
            const response = await fetch(entityUrl);
            
            if (response.ok) {
                const data = await response.json();
                this.entities = data.all || [];
                console.log(`Entity index loaded: ${this.entities.length} entities`);
            }
        } catch (error) {
            console.log('Entity index not available (optional):', error.message);
            this.entities = [];
        }
    }
    
    createAutocompleteDropdown() {
        // Dropdown-Container erstellen
        this.autocompleteDropdown = document.createElement('div');
        this.autocompleteDropdown.className = 'autocomplete-dropdown';
        this.autocompleteDropdown.style.display = 'none';
        
        // Nach dem Suchfeld einfügen
        const searchWrapper = this.searchInput.parentElement;
        searchWrapper.style.position = 'relative';
        searchWrapper.appendChild(this.autocompleteDropdown);
    }
    
    showAutocomplete(query) {
        const lowerQuery = query.toLowerCase();
        const suggestions = [];
        
        // 1. Institutionen aus dem Index suchen (eindeutige)
        const institutionSet = new Set();
        this.index.forEach(item => {
            if (item.institution && item.institution.toLowerCase().includes(lowerQuery)) {
                institutionSet.add(item.institution);
            }
        });
        
        institutionSet.forEach(inst => {
            suggestions.push({
                type: 'institution',
                name: inst,
                icon: '🏛️',
                label: 'Institution'
            });
        });
        
        // 2. Entities suchen (inkl. Varianten)
        this.entities.forEach(entity => {
            const matchesName = entity.name.toLowerCase().includes(lowerQuery);
            const matchesVariant = entity.search_terms?.some(term => 
                term.toLowerCase().includes(lowerQuery)
            );
            
            if (matchesName || matchesVariant) {
                // Prüfen ob nicht schon als Institution hinzugefügt
                if (!institutionSet.has(entity.name)) {
                    suggestions.push({
                        type: entity.type || 'entity',
                        name: entity.name,
                        icon: entity.type === 'institution' ? '🏛️' : '🔖',
                        label: entity.type === 'institution' ? 'Institution' : 'Entity',
                        variants: entity.variants
                    });
                }
            }
        });
        
        // 3. Kategorien suchen
        const categories = [...new Set(this.index.map(item => item.category_display))];
        categories.forEach(cat => {
            if (cat && cat.toLowerCase().includes(lowerQuery)) {
                suggestions.push({
                    type: 'category',
                    name: cat,
                    icon: '📁',
                    label: 'Kategorie'
                });
            }
        });
        
        // Max 8 Vorschläge anzeigen
        const limitedSuggestions = suggestions.slice(0, 8);
        
        if (limitedSuggestions.length > 0) {
            this.renderAutocomplete(limitedSuggestions);
            this.autocompleteDropdown.style.display = 'block';
            this.autocompleteVisible = true;
            this.selectedSuggestionIndex = -1;
        } else {
            this.hideAutocomplete();
        }
    }
    
    renderAutocomplete(suggestions) {
        this.autocompleteDropdown.innerHTML = suggestions.map((s, index) => `
            <div class="autocomplete-item" data-index="${index}" data-value="${this.escapeHtml(s.name)}">
                <span class="autocomplete-icon">${s.icon}</span>
                <span class="autocomplete-name">${this.highlightMatch(s.name, this.searchInput.value)}</span>
                <span class="autocomplete-type">${s.label}</span>
            </div>
        `).join('');
        
        // Click-Handler für Vorschläge
        this.autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', () => {
                const value = item.dataset.value;
                this.searchInput.value = value;
                this.hideAutocomplete();
                this.performSearch();
            });
            
            item.addEventListener('mouseenter', () => {
                this.selectedSuggestionIndex = parseInt(item.dataset.index);
                this.highlightSuggestion();
            });
        });
    }
    
    highlightMatch(text, query) {
        if (!query) return this.escapeHtml(text);
        const escaped = this.escapeHtml(text);
        const regex = new RegExp(`(${this.escapeRegex(query)})`, 'gi');
        return escaped.replace(regex, '<mark>$1</mark>');
    }
    
    navigateSuggestion(direction) {
        const items = this.autocompleteDropdown.querySelectorAll('.autocomplete-item');
        if (items.length === 0) return;
        
        this.selectedSuggestionIndex += direction;
        
        if (this.selectedSuggestionIndex < 0) {
            this.selectedSuggestionIndex = items.length - 1;
        } else if (this.selectedSuggestionIndex >= items.length) {
            this.selectedSuggestionIndex = 0;
        }
        
        this.highlightSuggestion();
    }
    
    highlightSuggestion() {
        const items = this.autocompleteDropdown.querySelectorAll('.autocomplete-item');
        items.forEach((item, index) => {
            if (index === this.selectedSuggestionIndex) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });
    }
    
    selectSuggestion(index) {
        const items = this.autocompleteDropdown.querySelectorAll('.autocomplete-item');
        if (items[index]) {
            const value = items[index].dataset.value;
            this.searchInput.value = value;
            this.hideAutocomplete();
            this.performSearch();
        }
    }
    
    hideAutocomplete() {
        this.autocompleteDropdown.style.display = 'none';
        this.autocompleteVisible = false;
        this.selectedSuggestionIndex = -1;
    }

    async loadIndex() {
        try {
            this.showLoading(true);

            // FIXED: Dynamischer Pfad zum Search-Index
            const indexUrl = `${this.urlPrefix}/assets/data/search-index.json`;
            console.log('Loading search index from:', indexUrl);

            const response = await fetch(indexUrl);

            if (!response.ok) {
                throw new Error(`Failed to load search index: ${response.status} ${response.statusText}`);
            }

            this.index = await response.json();
            console.log(`Search index loaded: ${this.index.length} items`);
            this.showLoading(false);

        } catch (error) {
            console.error('Error loading search index:', error);

            // Fallback: Versuche alternativen Pfad
            if (this.urlPrefix === '') {
                console.log('Trying fallback path with /public prefix...');
                try {
                    const fallbackUrl = '/public/assets/data/search-index.json';
                    const response = await fetch(fallbackUrl);
                    if (response.ok) {
                        this.index = await response.json();
                        this.urlPrefix = '/public'; // Update prefix für Links
                        console.log(`Search index loaded via fallback: ${this.index.length} items`);
                        this.showLoading(false);
                        return;
                    }
                } catch (fallbackError) {
                    console.error('Fallback also failed:', fallbackError);
                }
            }

            this.showError('Fehler beim Laden der Suchdaten. Bitte laden Sie die Seite neu.');
        }
    }

    performSearch() {
        const query = this.searchInput.value.trim();

        // Suche durchführen (auch bei leerem Query = alle anzeigen)
        const results = this.search(query);

        // Ergebnisse anzeigen
        this.displayResults(results, query);

        // URL aktualisieren (ohne Seite neu zu laden)
        const url = new URL(window.location);
        if (query) {
            url.searchParams.set('q', query);
        } else {
            url.searchParams.delete('q');
        }
        window.history.replaceState({}, '', url);
    }

    search(query) {
        const terms = query.toLowerCase().split(/\s+/).filter(t => t.length > 0);

        // Suche und Score berechnen
        const results = this.index.filter(item => {
            // Category filter - FIXED: Prüfe gegen category_id (internal_name) statt category (display_name)
            const categoryKey = item.category_id || item.category;
            if (!this.activeCategories.has(categoryKey)) {
                return false;
            }

            // Bei leerem Query alle (gefilterten) zurückgeben
            if (terms.length === 0) {
                return true;
            }

            // ERWEITERT: Volltext-Suche in ALLEN Feldern inkl. fulltext und entity_variants
            const searchText = [
                item.title || '',
                item.description || '',
                item.institution || '',
                item.category_display || item.category || '',
                item.fulltext || '',  // NEU: Volltext aus allen Feldern + Markdown
                (item.entity_variants || []).join(' ')  // NEU: Entity-Varianten
            ].join(' ').toLowerCase();

            return terms.every(term => searchText.includes(term));
        }).map(item => ({
            ...item,
            relevance: terms.length > 0 ? this.calculateRelevance(item, terms) : 50
        }));

        // Nach Relevanz sortieren (oder alphabetisch bei leerem Query)
        if (terms.length > 0) {
            results.sort((a, b) => b.relevance - a.relevance);
        } else {
            results.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
        }

        return results;
    }

    calculateRelevance(item, terms) {
        let score = 0;
        const title = (item.title || '').toLowerCase();
        const description = (item.description || '').toLowerCase();
        const institution = (item.institution || '').toLowerCase();
        const fulltext = (item.fulltext || '').toLowerCase();
        const entityVariants = (item.entity_variants || []).join(' ').toLowerCase();

        terms.forEach(term => {
            // Title matches haben höchste Priorität
            if (title.includes(term)) {
                score += 10;
                // Exakte Matches noch höher
                if (title === term) {
                    score += 20;
                }
                // Am Anfang des Titels
                if (title.startsWith(term)) {
                    score += 5;
                }
            }

            // Institution matches (hoch gewichtet)
            if (institution.includes(term)) {
                score += 8;
            }
            
            // Entity-Varianten (z.B. "HU Berlin" für "Humboldt-Universität")
            if (entityVariants.includes(term)) {
                score += 7;
            }

            // Description matches
            if (description.includes(term)) {
                score += 3;
            }
            
            // Fulltext matches (niedrigste Priorität, aber trotzdem gefunden)
            if (fulltext.includes(term)) {
                score += 1;
            }
        });

        return score;
    }

    displayResults(results, query) {
        this.currentResults = results;

        // Update header
        this.resultsCount.textContent = results.length;
        this.searchQuery.textContent = query ? `für "${query}"` : '(alle Einträge)';

        // Show/hide elements
        this.emptyState.style.display = 'none';
        this.noResultsState.style.display = 'none';
        this.resultsHeader.style.display = 'flex';

        if (this.clearSearchBtn) {
            this.clearSearchBtn.style.display = query ? 'block' : 'none';
        }

        if (results.length === 0) {
            this.noResultsState.style.display = 'block';
            this.resultsList.style.display = 'none';
            return;
        }

        // Render results
        this.resultsList.style.display = 'block';
        this.resultsList.innerHTML = results.map(item => this.renderResultItem(item, query)).join('');
    }

    renderResultItem(item, query) {
        // Highlight search terms in title and description
        const highlightedTitle = this.highlightTerms(item.title || 'Untitled', query);
        const highlightedDescription = this.highlightTerms(item.description || '', query);

        // Category icon
        let categoryIcon = '📊';
        const category = item.category || '';
        if (category === 'forschung') categoryIcon = '🔬';
        else if (category === 'services' || category === 'service') categoryIcon = '🤖';
        else if (category === 'lehre') categoryIcon = '📚';

        // Relevance bar
        const maxRelevance = this.currentResults.length > 0
            ? Math.max(...this.currentResults.map(r => r.relevance))
            : 100;
        const relevancePercent = maxRelevance > 0
            ? Math.round((item.relevance / maxRelevance) * 100)
            : 0;

        // FIXED: Korrekter URL-Aufbau
        // Die URL im Index ist relativ (z.B. "/details/xxx.html")
        // Wir müssen den urlPrefix hinzufügen
        let itemUrl = item.url || '';

        // Wenn URL bereits mit dem Präfix beginnt, nicht nochmal hinzufügen
        if (this.urlPrefix && !itemUrl.startsWith(this.urlPrefix)) {
            // Stelle sicher, dass kein doppelter Slash entsteht
            if (itemUrl.startsWith('/')) {
                itemUrl = this.urlPrefix + itemUrl;
            } else {
                itemUrl = this.urlPrefix + '/' + itemUrl;
            }
        }

        const institutionDisplay = item.institution || 'Keine Institution angegeben';
        const categoryDisplay = item.category_display || item.category || 'Kategorie';
        const categoryClass = item.category || 'default';
        
        // Institution als klickbaren Link (filtert Suche nach dieser Institution)
        const institutionHtml = item.institution 
            ? `<span class="institution-badge institution-link" onclick="searchInstance.searchByInstitution('${this.escapeHtml(item.institution)}')" title="Nach dieser Institution suchen">${this.escapeHtml(institutionDisplay)}</span>`
            : `<span class="institution-badge">${this.escapeHtml(institutionDisplay)}</span>`;

        return `
            <article class="search-result-item">
                <div class="result-header">
                    <div class="result-icon">${categoryIcon}</div>
                    <div class="result-main">
                        <h3 class="result-title">
                            <a href="${this.escapeHtml(itemUrl)}">${highlightedTitle}</a>
                        </h3>
                        <div class="result-meta">
                            <span class="category-badge category-badge-${this.escapeHtml(categoryClass)}">${this.escapeHtml(categoryDisplay)}</span>
                            ${institutionHtml}
                        </div>
                    </div>
                </div>
                <p class="result-description">${highlightedDescription || '<em>Keine Beschreibung verfügbar</em>'}</p>
                <div class="result-footer">
                    <div class="relevance-bar">
                        <div class="relevance-label">Relevanz:</div>
                        <div class="relevance-bar-container">
                            <div class="relevance-bar-fill" style="width: ${relevancePercent}%"></div>
                        </div>
                        <div class="relevance-percent">${relevancePercent}%</div>
                    </div>
                    <a href="${this.escapeHtml(itemUrl)}" class="result-link">Details →</a>
                </div>
            </article>
        `;
    }

    highlightTerms(text, query) {
        if (!text || !query) return text || '';

        const terms = query.toLowerCase().split(/\s+/).filter(t => t.length > 0);
        let result = this.escapeHtml(text);

        // Sort terms by length (longest first) to avoid partial replacements
        terms.sort((a, b) => b.length - a.length);

        terms.forEach(term => {
            const regex = new RegExp(`(${this.escapeRegex(term)})`, 'gi');
            result = result.replace(regex, '<mark>$1</mark>');
        });

        return result;
    }

    escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    updateFilters() {
        // Update active categories
        this.activeCategories.clear();
        this.categoryFilters.forEach(filter => {
            if (filter.checked) {
                this.activeCategories.add(filter.value);
            }
        });

        // Re-run search if there's a query
        if (this.searchInput.value.trim()) {
            this.performSearch();
        }
    }

    clearSearch() {
        this.searchInput.value = '';
        
        // Clear URL parameter
        const url = new URL(window.location);
        url.searchParams.delete('q');
        window.history.replaceState({}, '', url);
        
        // Alle Einträge anzeigen
        this.performSearch();
    }
    
    searchByInstitution(institution) {
        // Debounce-Timer abbrechen falls aktiv
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
            this.debounceTimer = null;
        }
        
        // Setze den Suchbegriff auf die Institution
        this.searchInput.value = institution;
        
        // Suche sofort ausführen
        this.performSearch();
        
        // Scroll nach oben
        this.searchInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
        this.searchInput.focus();
    }

    showEmptyState() {
        this.emptyState.style.display = 'block';
        this.noResultsState.style.display = 'none';
        this.resultsHeader.style.display = 'none';
        this.resultsList.style.display = 'none';

        if (this.clearSearchBtn) {
            this.clearSearchBtn.style.display = 'none';
        }
    }

    showLoading(show) {
        if (this.loadingState) {
            this.loadingState.style.display = show ? 'block' : 'none';
        }

        if (show) {
            this.emptyState.style.display = 'none';
            this.noResultsState.style.display = 'none';
            this.resultsList.style.display = 'none';
        }
    }

    showError(message) {
        this.showLoading(false);
        if (this.emptyState) {
            this.emptyState.style.display = 'block';
            const heading = this.emptyState.querySelector('h3');
            const paragraph = this.emptyState.querySelector('p');
            if (heading) heading.textContent = 'Fehler';
            if (paragraph) paragraph.textContent = message;
        }
    }
}

// Global instance for onclick handlers
let searchInstance = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    searchInstance = new Search();
});