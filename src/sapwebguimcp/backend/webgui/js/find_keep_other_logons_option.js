(params) => {
    // The radio button of SAP's "user already logged on" (multiple logon) page whose label says that the
    // user's other logons are kept. Returns that one element, or null when no option or more than one
    // option matches: the caller then does not continue, because continuing could end the other logons.
    const { texts } = params;
    const keep = new RegExp(texts.keepOtherLogons.source, texts.keepOtherLogons.flags);
    const controls = 'input, select, textarea, button';

    const labelOf = (radio) => {
        const parts = [];
        if (radio.labels) {
            for (const label of radio.labels) {
                parts.push(label.textContent || '');
            }
        }
        parts.push(radio.getAttribute('aria-label') || '');
        parts.push(radio.getAttribute('title') || '');
        const labelledBy = radio.getAttribute('aria-labelledby');
        if (labelledBy) {
            for (const id of labelledBy.split(/\s+/)) {
                const element = document.getElementById(id);
                if (element) {
                    parts.push(element.textContent || '');
                }
            }
        }
        // Plain text right after the radio button, up to the next form control.
        let text = '';
        for (let node = radio.nextSibling; node; node = node.nextSibling) {
            if (node.nodeType === Node.ELEMENT_NODE) {
                if (
                    node.matches(controls) ||
                    node.querySelector(controls) ||
                    node.tagName === 'BR'
                ) {
                    break;
                }
            }
            text += node.textContent || '';
        }
        parts.push(text);
        return parts.join(' ').replace(/\s+/g, ' ');
    };

    const matches = Array.from(document.querySelectorAll('input[type="radio"]')).filter((radio) =>
        keep.test(labelOf(radio))
    );
    return matches.length === 1 ? matches[0] : null;
};
