function pastedHtmlRows(html) {
  if (!html || typeof DOMParser === "undefined") return [];
  const documentFragment = new DOMParser().parseFromString(html, "text/html");
  const table = documentFragment.querySelector("table");
  if (!table) return [];
  return [...table.rows]
    .map((tableRow) => [...tableRow.cells].map((cell) => {
      const clone = cell.cloneNode(true);
      clone.querySelectorAll("br").forEach((breakNode) => breakNode.replaceWith("\n"));
      return clone.textContent.replace(/\u00a0/g, " ").trim();
    }))
    .filter((row) => row.some(Boolean));
}

function pastedRows(text, html = "") {
  const htmlRows = pastedHtmlRows(html);
  if (htmlRows.length) return htmlRows;

  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  let quoteClosed = false;
  const input = String(text || "").replace(/^\uFEFF/, "");

  for (let index = 0; index < input.length; index += 1) {
    const character = input[index];
    const nextCharacter = input[index + 1];

    if (quoted) {
      if (character === '"' && nextCharacter === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
        quoteClosed = true;
      } else {
        cell += character;
      }
      continue;
    }

    if (character === '"' && !quoteClosed && cell.trim() === "") {
      quoted = true;
      cell = "";
      continue;
    }

    if (character === "\t") {
      row.push(cell.trim());
      cell = "";
      quoteClosed = false;
      continue;
    }

    if (character === "\r" || character === "\n" || character === "\u2028" || character === "\u2029") {
      if (character === "\r" && nextCharacter === "\n") index += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = "";
      quoteClosed = false;
      continue;
    }

    cell += character;
  }

  if (cell || row.length) {
    row.push(cell.trim());
    if (row.some(Boolean)) rows.push(row);
  }
  return rows;
}

function normalized(value) {
  const halfWidth = String(value || "").replace(/[\uFF01-\uFF5E]/g, (character) => String.fromCharCode(character.charCodeAt(0) - 0xfee0));
  return [...halfWidth.toLowerCase()]
    .map((character) => traditionalToSimplified[character] || character)
    .join("")
    .replace(/m³/g, "m3")
    .replace(/[^a-z0-9\u3400-\u9fff]+/g, "");
}

function headerMatchScore(value, index) {
  const candidate = normalized(value);
  if (!candidate) return 0;
  const hasTotalMarker = /总|合计|total|totals|sum/.test(candidate);
  const hasPerPieceMarker = /每件|单件|件|perpiece|perunit|unit|package|carton/.test(candidate);
  const isPerPieceWeightField = index === 15 || index === 16;
  const isTotalWeightField = index === 22 || index === 23;
  const isUnitVolumeField = index === 17;
  const isTotalVolumeField = index === 24;
  return Math.max(...headerAliases[index].map((alias) => {
    const normalizedAlias = normalized(alias);
    if (!normalizedAlias) return 0;
    let score = 0;
    if (candidate === normalizedAlias) score = 100 + normalizedAlias.length / 100;
    else if (candidate.includes(normalizedAlias)) score = 80 + normalizedAlias.length / 100;
    else if (normalizedAlias.includes(candidate) && candidate.length >= 2) score = 60 + candidate.length / 100;
    if (!score) return 0;
    if (isPerPieceWeightField) score += hasPerPieceMarker ? 18 : -18;
    if (isTotalWeightField) score += hasTotalMarker ? 18 : (hasPerPieceMarker ? -24 : 0);
    if (isUnitVolumeField) score += hasPerPieceMarker ? 18 : -18;
    if (isTotalVolumeField) score += hasTotalMarker ? 18 : (hasPerPieceMarker ? -24 : 0);
    return score;
  }));
}

function findHeaderMap(row) {
  const pairs = [];
  row.forEach((cell, sourceIndex) => {
    headers.forEach((_, targetIndex) => {
      const score = headerMatchScore(cell, targetIndex);
      if (score > 0) pairs.push({ sourceIndex, targetIndex, score });
    });
  });
  pairs.sort((left, right) => right.score - left.score || left.targetIndex - right.targetIndex || left.sourceIndex - right.sourceIndex);
  const usedSources = new Set();
  const usedTargets = new Set();
  const byTarget = Array(headers.length).fill(-1);
  pairs.forEach(({ sourceIndex, targetIndex, score }) => {
    if (score < 60 || usedSources.has(sourceIndex) || usedTargets.has(targetIndex)) return;
    usedSources.add(sourceIndex);
    usedTargets.add(targetIndex);
    byTarget[targetIndex] = sourceIndex;
  });
  return usedTargets.size >= 2 ? { byTarget, matchedTargets: [...usedTargets] } : null;
}

function findHeaderInfo(rows) {
  const maxHeaderRows = Math.min(rows.length, 6);
  for (let rowIndex = 0; rowIndex < maxHeaderRows; rowIndex += 1) {
    const map = findHeaderMap(rows[rowIndex]);
    if (map) return { map, rowIndex };
  }
  return null;
}

function parsePaste(text,html='',startColumn=0) {
  const raw=pastedRows(text,html);const info=findHeaderInfo(raw);
  const data=info?raw.slice(info.rowIndex+1):raw;
  const original=!info&&startColumn===0&&data.every(row=>row.length>=30);
  const startIndex=Math.max(0,displayColumns.indexOf(startColumn));
  const columns=info?info.map.matchedTargets:original?Array.from({length:30},(_,i)=>i):displayColumns.slice(startIndex,startIndex+Math.max(0,...data.map(row=>row.length)));
  const entries=data.map(row=>{
    const full=emptyRow();
    // Each row keeps its own footprint: omitted cells must not erase existing data.
    const rowColumns=columns.filter((column,index)=>(info?info.map.byTarget[column]:index)<row.length);
    rowColumns.forEach(column=>{const sourceIndex=info?info.map.byTarget[column]:columns.indexOf(column);full[column]=row[sourceIndex]||'';});
    return {row:full,columns:rowColumns};
  }).filter(entry=>entry.row.some(value=>!blank(value)));
  return {rows:entries.map(entry=>entry.row),rowColumns:entries.map(entry=>entry.columns),columns,headerRow:info?info.rowIndex+1:null,matched:columns.length,missing:info?[20,23,25].filter(column=>!columns.includes(column)&&!(column===23&&columns.includes(16))&&!(column===25&&columns.includes(26))):[]};
}

function applyPaste(currentRows,text,html='',startRow=0,startColumn=0) {
  const parsed=parsePaste(text,html,startColumn);const rows=currentRows.map(normalizeRow);
  parsed.rows.forEach((row,offset)=>{
    while(rows.length<=startRow+offset)rows.push(emptyRow());
    parsed.rowColumns[offset].forEach(column=>rows[startRow+offset][column]=row[column]);
  });
  if(!rows.length||rows[rows.length-1].some(value=>!blank(value)))rows.push(emptyRow());
  return {...parsed,rows,count:parsed.rows.length};
}
