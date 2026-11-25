() => {
    const fields = [];

    /**
     * Get label text for an input element.
     * SAP uses various methods to associate labels with inputs.
     */
    function getLabel(el) {
        // 1. Title attribute (SAP uses this for field descriptions)
        const title = el.getAttribute('title');
        if (title) {
            return title.substring(0, 100);
        }

        // 2. aria-labelledby reference
        const ariaLabelledBy = el.getAttribute('aria-labelledby');
        if (ariaLabelledBy) {
            const labelEl = document.getElementById(ariaLabelledBy);
            if (labelEl) {
                return labelEl.textContent.trim().substring(0, 100);
            }
        }

        // 3. Standard label element
        if (el.id) {
            const label = document.querySelector(`label[for="${el.id}"]`);
            if (label) {
                return label.textContent.trim().substring(0, 100);
            }
        }

        // 4. SAP-specific: look for label with lsdata["1"] pointing to this input's ID
        if (el.id) {
            const labels = document.querySelectorAll('label[lsdata]');
            for (const label of labels) {
                try {
                    const lsdata = JSON.parse(label.getAttribute('lsdata'));
                    if (lsdata['1'] === el.id && lsdata['3']) {
                        return lsdata['3'].substring(0, 100);
                    }
                } catch {
                    // Ignore parsing errors
                }
            }
        }

        // 5. Look for nearby text in parent
        const parent = el.parentElement;
        if (parent) {
            const prevSibling = el.previousElementSibling;
            if (prevSibling && prevSibling.tagName !== 'INPUT') {
                const text = prevSibling.textContent.trim();
                if (text.length > 0 && text.length < 100) {
                    return text;
                }
            }
        }

        return '';
    }

    /**
     * Determine field type from SAP control type attribute.
     */
    function getFieldType(el) {
        const ct = el.getAttribute('ct');

        // ComboBox/Dropdown - only ct=CB is a true dropdown
        // ct=CBS (ComboBox with Server) is an autocomplete field, NOT a dropdown
        if (ct === 'CB') {
            return 'dropdown';
        }

        // Checkbox
        if (ct === 'CHK' || el.type === 'checkbox') {
            return 'checkbox';
        }

        // Radio button
        if (ct === 'RB' || el.type === 'radio') {
            return 'radio';
        }

        // Default to text
        return 'text';
    }

    /**
     * State of a checkbox/radio that is not an <input>: aria-checked first, then the lsCheckBox--checked /
     * lsRadioButton--unchecked class modifiers (also with a --disabled suffix). null when it cannot be told.
     */
    function getSelectorState(el) {
        const aria = el.getAttribute('aria-checked');
        if (aria === 'true') {
            return true;
        }
        if (aria === 'false') {
            return false;
        }
        if (aria !== null) {
            return null; // 'mixed' or anything else
        }
        for (const token of Array.from(el.classList)) {
            const match = /^ls(?:CheckBox|RadioButton)--(checked|unchecked)(?:--|$)/.exec(token);
            if (match) {
                return match[1] === 'checked';
            }
        }
        return null;
    }

    /**
     * Name of a checkbox/radio that is not an <input>. Deliberately no sibling-text guessing (see getLabel):
     * unnamed controls (table and ABAP list checkboxes) cannot be addressed by name and are left out.
     */
    function getSelectorLabel(el) {
        const candidates = [
            el.getAttribute('aria-label'),
            el.textContent,
            el.getAttribute('title'),
        ];
        for (const candidate of candidates) {
            const text = (candidate || '').trim();
            if (text) {
                return text.substring(0, 100);
            }
        }
        return '';
    }

    // Find all input elements
    document.querySelectorAll('input, select').forEach((el) => {
        // An <input> inside a checkbox/radio wrapper (ARIA role or lsCheckBox/lsRadioButton class) is reported
        // through the wrapper (second loop)
        const wrapper = el.closest(
            '[role="checkbox"], [role="radio"], .lsCheckBox, .lsRadioButton'
        );
        if (wrapper && wrapper !== el) {
            return;
        }

        // Skip hidden and submit buttons
        if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') {
            return;
        }

        // Skip if not visible
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            return;
        }

        // Skip if in a hidden container
        if (el.offsetParent === null) {
            return;
        }

        const fieldType = getFieldType(el);
        const isReadonly = el.readOnly || el.disabled || el.hasAttribute('readonly');

        const field = {
            id: el.id || '',
            label: getLabel(el),
            field_type: fieldType,
            current_value: el.value || null,
            checked: fieldType === 'checkbox' || fieldType === 'radio' ? el.checked : null,
            readonly: isReadonly,
            options: null, // Will be populated separately for dropdowns if requested
        };

        // Only include fields with an ID (needed for targeting)
        if (field.id) {
            fields.push(field);
        }
    });

    // Checkboxes and radio buttons that are no <input>: ARIA role elements and SAP lsCheckBox/lsRadioButton spans
    const selectorControls = document.querySelectorAll(
        '[role="checkbox"], [role="radio"], .lsCheckBox, .lsRadioButton'
    );
    selectorControls.forEach((el) => {
        if (el.tagName === 'INPUT' || el.tagName === 'SELECT') {
            return; // handled by the first loop
        }

        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            return;
        }
        if (el.offsetParent === null) {
            return;
        }

        const classes = Array.from(el.classList);
        const isRadio = el.getAttribute('role') === 'radio' || classes.includes('lsRadioButton');
        const isReadonly =
            el.getAttribute('aria-disabled') === 'true' ||
            el.getAttribute('aria-readonly') === 'true' ||
            classes.some((token) => token.endsWith('--disabled') || token.endsWith('--readonly'));

        const field = {
            id: el.id || '',
            label: getSelectorLabel(el),
            field_type: isRadio ? 'radio' : 'checkbox',
            current_value: null,
            checked: getSelectorState(el),
            readonly: isReadonly,
            options: null,
        };

        // Only named controls with an ID (an unnamed one cannot be addressed by sap_set_checkbox)
        if (field.id && field.label) {
            fields.push(field);
        }
    });

    return fields;
};
