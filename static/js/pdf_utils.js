// static/js/pdf_utils.js

/**
 * Helper to download PDF with "Save As" prompt
 * @param {string} url - The URL to fetch the PDF from.
 * @param {string} assignedFilename - The suggested filename for saving.
 * @returns {Promise<boolean>} - True if successful, false otherwise.
 */
async function downloadPdfWithPrompt(url, assignedFilename) {
    try {
        // 1. Fetch the PDF blob
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Network response was not ok');
        const blob = await resp.blob();

        // 2. Try using the File System Access API (active "Save As")
        if (window.showSaveFilePicker) {
            try {
                const handle = await window.showSaveFilePicker({
                    suggestedName: assignedFilename,
                    types: [{
                        description: 'PDF Document',
                        accept: { 'application/pdf': ['.pdf'] },
                    }],
                });
                const writable = await handle.createWritable();
                await writable.write(blob);
                await writable.close();
                return true; // Success
            } catch (err) {
                if (err.name === 'AbortError') {
                    return false; // User cancelled
                }
                // If other error, fall back
                console.warn("File System Access API failed, falling back", err);
            }
        }

        // 3. Fallback: classic download
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = assignedFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
        return true;

    } catch (error) {
        console.error('Download failed:', error);
        alert("Greška pri preuzimanju PDF-a.");
        return false;
    }
}
