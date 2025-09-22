// ATS Screening Report - JavaScript functionality

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all functionality
    initRevealAnimations();
    initChartAnimations();
    initButtonHandlers();
});

// Reveal animations using Intersection Observer
function initRevealAnimations() {
    const revealElements = document.querySelectorAll('.reveal');
    
    const revealObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate');
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });
    
    revealElements.forEach(element => {
        revealObserver.observe(element);
    });
}

// Chart bar animations
function initChartAnimations() {
    const chartBars = document.querySelectorAll('.chart-bar');
    
    const chartObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                animateChartBar(entry.target);
            }
        });
    }, {
        threshold: 0.5
    });
    
    chartBars.forEach(bar => {
        chartObserver.observe(bar);
    });
}

function animateChartBar(barElement) {
    const value = parseInt(barElement.dataset.value);
    const maxValue = parseInt(barElement.dataset.max);
    const height = (value / maxValue) * 200; // 200px is max height
    
    // Set initial height to 0 for animation
    barElement.style.height = '0px';
    
    // Animate to final height
    setTimeout(() => {
        barElement.style.height = height + 'px';
    }, 100);
}

// Button click handlers
function initButtonHandlers() {
    // Download Report button
    const downloadBtn = document.querySelector('.btn-primary');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', handleDownload);
    }
    
    // Contact CTA button
    const ctaBtn = document.querySelector('.btn-cta');
    if (ctaBtn) {
        ctaBtn.addEventListener('click', handleContact);
    }
}

function handleDownload(event) {
    event.preventDefault();
    
    // Add visual feedback
    const button = event.currentTarget;
    const originalText = button.innerHTML;
    
    button.innerHTML = '<span>📄</span><span class="ml-2">Downloading...</span>';
    button.style.opacity = '0.7';
    button.style.pointerEvents = 'none';
    
    // Simulate download process
    setTimeout(() => {
        // In a real application, this would trigger an actual download
        alert('Download functionality would be implemented here.\n\nThis would generate and download a PDF version of the ATS screening report.');
        
        // Reset button
        button.innerHTML = originalText;
        button.style.opacity = '1';
        button.style.pointerEvents = 'auto';
    }, 1500);
}

function handleContact(event) {
    event.preventDefault();
    
    // Add visual feedback
    const button = event.currentTarget;
    const originalText = button.innerHTML;
    
    button.innerHTML = '<span>📞</span><span class="ml-2">Opening contact...</span>';
    button.style.opacity = '0.7';
    button.style.pointerEvents = 'none';
    
    // Simulate contact action
    setTimeout(() => {
        // In a real application, this might open a contact form or redirect to contact page
        alert('Contact functionality would be implemented here.\n\nThis could:\n• Open a contact form\n• Redirect to a contact page\n• Open email client\n• Show phone number');
        
        // Reset button
        button.innerHTML = originalText;
        button.style.opacity = '1';
        button.style.pointerEvents = 'auto';
    }, 1000);
}

// Smooth scrolling for internal links (if needed)
function smoothScrollTo(target) {
    const element = document.querySelector(target);
    if (element) {
        element.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
    }
}

// Add some interactive enhancements
function addInteractiveEnhancements() {
    // Add hover effects to cards
    const bentoCards = document.querySelectorAll('.bento-card');
    bentoCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-2px)';
            this.style.boxShadow = '0 4px 20px hsl(220 25% 9% / 0.1)';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0)';
            this.style.boxShadow = 'var(--shadow-bento)';
        });
    });
    
    // Add click animation to buttons
    const buttons = document.querySelectorAll('.btn');
    buttons.forEach(button => {
        button.addEventListener('click', function() {
            this.style.transform = 'scale(0.98)';
            setTimeout(() => {
                this.style.transform = 'scale(1)';
            }, 100);
        });
    });
}

// Initialize interactive enhancements when DOM is ready
document.addEventListener('DOMContentLoaded', addInteractiveEnhancements);

// Performance monitoring (optional)
function logPerformanceMetrics() {
    if ('performance' in window) {
        window.addEventListener('load', () => {
            setTimeout(() => {
                const navigation = performance.getEntriesByType('navigation')[0];
                console.log('Page Load Time:', navigation.loadEventEnd - navigation.loadEventStart, 'ms');
                
                const paintEntries = performance.getEntriesByType('paint');
                paintEntries.forEach(entry => {
                    console.log(entry.name + ':', entry.startTime, 'ms');
                });
            }, 0);
        });
    }
}

// Initialize performance monitoring
logPerformanceMetrics();