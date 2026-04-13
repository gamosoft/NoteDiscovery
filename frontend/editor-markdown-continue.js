/**
 * Markdown editor helpers: Enter continues blockquotes, bullets, ordered lists, and task lists.
 * Plain functions only; no DOM. Used by app.js handleEditorEnterKey.
 */
(function (global) {
    'use strict';

    /**
     * True if cursor position lies inside a ``` fenced code block (toggle per line).
     */
    function cursorInMarkdownCodeFence(text, pos) {
        const before = text.slice(0, pos);
        let lineStart = 0;
        let inFence = false;
        for (;;) {
            const nl = before.indexOf('\n', lineStart);
            const end = nl === -1 ? before.length : nl;
            const line = before.slice(lineStart, end);
            const trimmed = line.trimStart();
            if (trimmed.startsWith('```')) {
                inFence = !inFence;
            }
            if (nl === -1) break;
            lineStart = nl + 1;
        }
        return inFence;
    }

    function getLineBounds(text, pos) {
        const lineStart = text.lastIndexOf('\n', Math.max(0, pos - 1)) + 1;
        let lineEnd = text.indexOf('\n', pos);
        if (lineEnd === -1) lineEnd = text.length;
        return {
            lineStart,
            lineEnd,
            line: text.slice(lineStart, lineEnd),
        };
    }

    /**
     * @returns {{ continuePrefix: string, isEmpty: boolean } | null}
     */
    function parseContinuationContext(line) {
        const quoteMatch = line.match(/^(\s*)((?:>\s*)+)/);
        let quoteFull = '';
        let rest = line;
        if (quoteMatch) {
            quoteFull = quoteMatch[1] + quoteMatch[2];
            rest = line.slice(quoteMatch[0].length);
        }

        const taskMatch = rest.match(/^(\s*)([-*+])\s+\[([xX ])\]\s*(.*)$/);
        if (taskMatch) {
            const inner = taskMatch[1];
            const ch = taskMatch[2];
            const mark = taskMatch[3];
            const cont = taskMatch[4];
            const marker = ch + ' [' + mark + '] ';
            const isEmpty = cont.trim() === '';
            return { continuePrefix: quoteFull + inner + marker, isEmpty };
        }

        const bulletMatch = rest.match(/^(\s*)([-*+])\s+(.*)$/);
        if (bulletMatch) {
            const inner = bulletMatch[1];
            const ch = bulletMatch[2];
            const cont = bulletMatch[3];
            const marker = ch + ' ';
            const isEmpty = cont.trim() === '';
            return { continuePrefix: quoteFull + inner + marker, isEmpty };
        }

        const orderedMatch = rest.match(/^(\s*)(\d+)([.)])\s+(.*)$/);
        if (orderedMatch) {
            const inner = orderedMatch[1];
            const num = parseInt(orderedMatch[2], 10);
            const sep = orderedMatch[3];
            const cont = orderedMatch[4];
            const marker = (num + 1) + sep + ' ';
            const isEmpty = cont.trim() === '';
            return { continuePrefix: quoteFull + inner + marker, isEmpty };
        }

        if (quoteFull) {
            const isEmpty = rest.trim() === '';
            return { continuePrefix: quoteFull, isEmpty };
        }

        return null;
    }

    /**
     * @param {string} text
     * @param {number} selStart
     * @param {number} selEnd
     * @param {KeyboardEvent} event
     * @returns {{ handled: false } | { handled: true, text: string, cursor: number }}
     */
    function tryEnter(text, selStart, selEnd, event) {
        if (event.key !== 'Enter') return { handled: false };
        if (event.defaultPrevented) return { handled: false };
        if (event.isComposing) return { handled: false };
        if (event.shiftKey) return { handled: false };
        if (event.ctrlKey || event.metaKey || event.altKey) return { handled: false };
        if (selStart !== selEnd) return { handled: false };
        if (cursorInMarkdownCodeFence(text, selStart)) return { handled: false };

        const { lineStart, lineEnd, line } = getLineBounds(text, selStart);
        if (selStart !== lineEnd) return { handled: false };

        const lineForParse = line.replace(/\r/g, '');
        const ctx = parseContinuationContext(lineForParse);
        if (!ctx) return { handled: false };

        if (ctx.isEmpty) {
            let delEnd = lineEnd;
            if (delEnd < text.length && text.charAt(delEnd) === '\n') {
                delEnd += 1;
            }
            const newText = text.slice(0, lineStart) + text.slice(delEnd);
            return { handled: true, text: newText, cursor: lineStart };
        }

        const insert = '\n' + ctx.continuePrefix;
        const newText = text.slice(0, lineEnd) + insert + text.slice(lineEnd);
        return { handled: true, text: newText, cursor: lineEnd + insert.length };
    }

    global.EditorMarkdownContinue = {
        tryEnter,
        parseContinuationContext,
        getLineBounds,
        cursorInMarkdownCodeFence,
    };
})(typeof window !== 'undefined' ? window : globalThis);
