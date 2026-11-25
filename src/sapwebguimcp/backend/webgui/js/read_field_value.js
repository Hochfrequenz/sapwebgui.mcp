(args) => {
    // Note: findInputByLabel is provided by find_field_utils.js (concatenated before this file)
    // Returns the trimmed value of the first label that resolves to exactly one field with a
    // non-empty value, else null. Unknown and ambiguous labels are skipped.
    for (const label of args.labels) {
        const result = findInputByLabel(label);
        if (result === null || result.ambiguous) {
            continue;
        }
        const value = String((result.element && result.element.value) || '').trim();
        if (value) {
            return value;
        }
    }
    return null;
};
