() => {
    const info = {
        transaction: '',
        title: document.title,
        url: window.location.href,
        program: '',
        dynpro: '',
        systemName: '',
        client: '',
        user: '',
    };

    // The WebGUI system-information menu carries language-independent element IDs; the value is
    // in the "13" key of the lsdata JSON (the aria-label also carries the field label, so it is no fallback).
    const sysInfo = (suffix) => {
        const el = document.getElementById('sysInfoAreaMenuItemSAPITS_MBAR_' + suffix);
        if (!el) return '';
        try {
            const data = JSON.parse(el.getAttribute('lsdata') || '{}');
            return data['13'] ? String(data['13']).trim() : '';
        } catch (e) {
            return '';
        }
    };
    // System reads "SID (client)", e.g. "DEV (100)".
    const systemMatch = sysInfo('SYSTEM').match(/^(.*?)\s*\(\d+\)$/);
    info.systemName = systemMatch ? systemMatch[1].trim() : sysInfo('SYSTEM');
    info.client = sysInfo('CLIENT');
    info.user = sysInfo('USER');
    // Dynpro reads "PROGRAM/0101"; the program name may itself contain slashes (namespaces).
    const dynproValue = sysInfo('DYNPRO');
    const slash = dynproValue.lastIndexOf('/');
    if (slash > 0) {
        info.program = dynproValue.slice(0, slash);
        info.dynpro = dynproValue.slice(slash + 1);
    } else {
        info.program = dynproValue;
    }
    info.transaction = sysInfo('TRANSACTION');

    // Try to find transaction code from various locations
    // OK-Code field might contain current transaction
    const okCodeField = document.querySelector('#ToolbarOkCode, input[id*="okcode" i]');
    if (okCodeField && okCodeField.value) {
        info.transaction = info.transaction || okCodeField.value.replace(/^\/[no]/, '');
    }

    // Check title bar for transaction info
    // SAP often shows "Transaction - Description" or similar
    const titleMatch = document.title.match(/^([A-Z0-9_\/]+)\s*[-:]|\(([A-Z0-9_]+)\)/);
    if (titleMatch) {
        info.transaction = info.transaction || (titleMatch[1] || titleMatch[2] || '').trim();
    }

    // Look for technical info in hidden fields or data attributes
    const techInfo = document.querySelector(
        '[data-program], [data-dynpro], [data-tcode], ' +
            'input[name*="program" i], input[name*="dynpro" i]'
    );
    if (techInfo && !info.program) {
        info.program = techInfo.getAttribute('data-program') || techInfo.getAttribute('name') || '';
        info.dynpro = techInfo.getAttribute('data-dynpro') || '';
    }

    // Try to extract from URL if it contains transaction info
    const urlMatch = window.location.href.match(/[?&](?:tcode|transaction)=([^&]+)/i); // lang-ok: URL parameter names
    if (urlMatch) {
        info.transaction = info.transaction || urlMatch[1];
    }

    return info;
};
