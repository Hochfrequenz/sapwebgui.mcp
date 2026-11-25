(params) => {
    const { startRow, endRow, maxRows } = params;

    /**
     * Escape special CSS characters for use in selectors.
     * SAP ALV grids use IDs like "grid#C120#1,2#if" which need escaping.
     */
    function escapeCssSelector(id) {
        return (
            '#' +
            id
                .split('')
                .map((char) => (':[]#,'.includes(char) ? '\\' + char : char))
                .join('')
        );
    }

    /**
     * Check if a cell element is a clickable hotspot.
     * Hotspots have lsdata["23"] = "UNDERLINE_HOTSPOT".
     */
    function isHotspotCell(element) {
        const lsdata = element.getAttribute('lsdata');
        if (!lsdata) return false;
        try {
            const parsed = JSON.parse(lsdata);
            return parsed['23'] === 'UNDERLINE_HOTSPOT';
        } catch {
            return lsdata.includes('UNDERLINE_HOTSPOT');
        }
    }

    /**
     * Row count the Web GUI reports for a grid or table control, or null.
     * The Web GUI renders only part of a long ALV grid (rows 1..90 of 300 right after execution) and only a
     * window of a table control, so the rows in the DOM are not the rows of the grid. The count sits in the
     * lsdata of the table: lsdata["34"].totalRows (ALV grid) or lsdata["34"].rowCount (table control).
     */
    function gridRowCount(table) {
        const lsdata = table.getAttribute('lsdata');
        if (!lsdata) return null;
        let control;
        try {
            control = JSON.parse(lsdata)['34'];
        } catch {
            return null;
        }
        if (!control || typeof control !== 'object') return null;
        for (const key of ['totalRows', 'rowCount']) {
            const value = control[key];
            if (Number.isInteger(value) && value >= 0) return value;
        }
        return null;
    }

    /**
     * Extract data from SAP ALV grid (table with ct="STCS").
     */
    function extractAlvGrid(alvTable) {
        const tableId = alvTable.id;
        const headers = [];
        const rows = [];
        const hotspotColumns = [];
        const columnMap = {};

        // Parse selection mode from lsdata
        let selectionMode = 'NONE';
        const tableLsdata = alvTable.getAttribute('lsdata');
        if (tableLsdata) {
            try {
                const parsed = JSON.parse(tableLsdata);
                if (parsed['10']) selectionMode = parsed['10'];
            } catch {
                // Ignore parse errors
            }
        }

        // Find header cells (row 0 in grid pattern)
        // Headers are in elements like grid#C120#0,1, grid#C120#0,2, etc.
        let colIdx = 0;
        while (true) {
            const headerCell = document.getElementById(`grid#${tableId}#0,${colIdx}`);
            if (!headerCell) break;

            const headerText = headerCell.textContent.trim().substring(0, 50);
            headers.push(headerText);
            columnMap[headerText] = colIdx;

            // Check if this column has hotspots by checking first data row
            const firstDataCell = document.getElementById(`grid#${tableId}#1,${colIdx}#if`);
            if (firstDataCell && isHotspotCell(firstDataCell)) {
                hotspotColumns.push(colIdx);
            }

            colIdx++;
        }

        // If no grid# pattern headers found, fall back to DOM traversal
        if (headers.length === 0) {
            const headerCells = alvTable.querySelectorAll('[role="columnheader"], th');
            headerCells.forEach((cell, idx) => {
                const text = cell.textContent.trim().substring(0, 50);
                headers.push(text);
                columnMap[text] = idx;
            });
        }

        // Extract data rows
        const maxEnd = startRow + maxRows - 1;
        const actualEndRow = endRow ? Math.min(endRow, maxEnd) : maxEnd;

        // Whether the loop ended at a row whose cells are in the DOM but hold no data: the data ended there
        // (e.g. the blank input lines of an editable table control, which its rowCount may count). Other ways to
        // end: the row limit, or a row whose cells are not rendered at all.
        let endedInDom = false;

        for (let rowNum = startRow; rowNum <= actualEndRow; rowNum++) {
            const rowData = {};
            const cellsInfo = {};
            let hasData = false;
            let inDom = false;

            for (let col = 0; col < headers.length; col++) {
                const headerName = headers[col] || `col_${col + 1}`;

                // Try grid# pattern first (SAP ALV standard), then bracket
                // notation tableId[row,col] (used by SE24 editable grids).
                const gridCellId = `grid#${tableId}#${rowNum},${col}`;
                const gridSpanId = `${gridCellId}#if`;
                const bracketCellId = `${tableId}[${rowNum},${col}]`;

                let cellElement =
                    document.getElementById(gridCellId) || document.getElementById(bracketCellId);
                let innerSpan = document.getElementById(gridSpanId);
                const cellId = cellElement ? cellElement.id : gridCellId;
                if (cellElement || innerSpan) inDom = true;

                // Get cell text — for editable grids (e.g., SE24 methods),
                // cells contain <input> elements whose values are not in textContent.
                let cellText = '';
                if (innerSpan) {
                    cellText = innerSpan.textContent.trim().substring(0, 200);
                } else if (cellElement) {
                    cellText = cellElement.textContent.trim().substring(0, 200);
                }
                if (!cellText && cellElement) {
                    const input = cellElement.querySelector('input, textarea');
                    if (input) cellText = (input.value || '').trim().substring(0, 200);
                }

                if (cellText) {
                    rowData[headerName] = cellText;
                    hasData = true;

                    // Determine click target and build selector
                    // Use Boolean() to ensure we return true/false, not null/undefined
                    const isHotspot = Boolean(innerSpan && isHotspotCell(innerSpan));
                    const clickTarget = isHotspot ? gridSpanId : cellId;
                    const selector = escapeCssSelector(clickTarget);

                    cellsInfo[headerName] = {
                        selector: selector,
                        clickable: true,
                        hotspot: isHotspot,
                    };
                }
            }

            if (hasData) {
                rows.push({
                    row: rowNum,
                    data: rowData,
                    cells: cellsInfo,
                });
            } else {
                // No more data rows
                endedInDom = inDom;
                break;
            }
        }

        // Rows of the requested range that exist in the grid but were not read: the Web GUI did not render
        // them, or the read stopped at the row limit. end_row not given means everything up to the row limit.
        // totalRows counts up to the last row returned (not startRow - 1 rows when start_row is beyond the total).
        // A rendered row without text ends the data: the rowCount of an editable table control counts its blank
        // input lines, which are not rows.
        const lastReturned = rows.length > 0 ? rows[rows.length - 1].row : 0;
        const lastRead = rows.length > 0 ? lastReturned : startRow - 1;
        const gridTotal = gridRowCount(alvTable);
        const requestedEnd = endRow ? endRow : Infinity;
        let totalRows;
        let truncated;
        if (gridTotal === null) {
            // No count reported: the rows read are all we know of
            totalRows = rows.length;
            truncated = false;
        } else if (endedInDom) {
            // The data ended inside the DOM; the reported count may include blank lines
            totalRows = lastReturned;
            truncated = false;
        } else {
            totalRows = Math.max(gridTotal, lastReturned);
            truncated = lastRead < Math.min(requestedEnd, gridTotal);
        }

        return {
            headers: headers,
            rows: rows,
            totalRows: totalRows,
            truncated: truncated,
            startRow: startRow,
            endRow: rows.length > 0 ? rows[rows.length - 1].row : startRow,
            alv: {
                table_id: tableId,
                selection_mode: selectionMode,
                hotspot_columns: hotspotColumns,
                column_map: columnMap,
            },
        };
    }

    /**
     * Extract data from a regular (non-ALV) table.
     */
    function extractRegularTable(table) {
        const headers = [];
        const headerCells = table.querySelectorAll("th, [role='columnheader']");
        headerCells.forEach((cell) => {
            const text = cell.textContent.trim().substring(0, 50);
            headers.push(text);
        });

        // If no headers found in th, try first row
        if (headers.length === 0) {
            const firstRow = table.querySelector('tr');
            if (firstRow) {
                firstRow.querySelectorAll('td').forEach((cell) => {
                    const text = cell.textContent.trim().substring(0, 50);
                    headers.push(text);
                });
            }
        }

        // Get rows with limits
        const rows = [];
        const dataRows = table.querySelectorAll("tbody tr, tr[role='row']");
        const maxEnd = startRow + maxRows - 1;
        const actualEndRow = endRow ? Math.min(endRow, maxEnd) : Math.min(dataRows.length, maxEnd);

        // Track which columns have data
        const columnsWithData = new Set();

        for (let i = startRow - 1; i < Math.min(actualEndRow, dataRows.length); i++) {
            const row = dataRows[i];
            if (!row) continue;

            const cells = row.querySelectorAll("td, [role='gridcell']");
            const rowData = {};

            cells.forEach((cell, idx) => {
                let cellText = cell.textContent.trim().substring(0, 200);
                // For editable grids (e.g., SE24 methods), cells contain input elements
                // whose values are not captured by textContent.
                if (!cellText) {
                    const input = cell.querySelector('input, textarea');
                    if (input) cellText = (input.value || '').trim().substring(0, 200);
                }
                if (cellText) {
                    const headerName = headers[idx] || `col_${idx + 1}`;
                    rowData[headerName] = cellText;
                    columnsWithData.add(headerName);
                }
            });

            if (Object.keys(rowData).length > 0) {
                rows.push({ row: i + 1, data: rowData });
            }
        }

        // Filter headers to only include columns that have data
        const usedHeaders = headers.filter(
            (h, idx) => columnsWithData.has(h) || columnsWithData.has(`col_${idx + 1}`)
        );

        return {
            headers: usedHeaders,
            totalRows: dataRows.length,
            returnedRows: rows.length,
            // Only the row limit can cut the requested range short; rows after end_row are not part of it
            truncated: Math.min(dataRows.length, endRow || Infinity) > actualEndRow,
            rows: rows,
            // Same bounds as an ALV grid, so a truncated read can go on with start_row = end_row + 1
            startRow: startRow,
            endRow: rows.length > 0 ? rows[rows.length - 1].row : startRow,
        };
    }

    // Main logic: detect ALV grid first, then fall back to regular table
    const alvTable = document.querySelector('table[ct="STCS"]');
    if (alvTable) {
        return extractAlvGrid(alvTable);
    }

    // Find regular table elements
    const tableSelectors = [
        'table[role="grid"]',
        '.sapMList table',
        'table.urTbl',
        '[role="treegrid"]',
        'table',
    ];

    let table = null;
    for (const selector of tableSelectors) {
        table = document.querySelector(selector);
        if (table) break;
    }

    if (!table) {
        return { error: 'No table found on current screen' };
    }

    return extractRegularTable(table);
};
