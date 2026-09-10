import re


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        """(el) => {
          const pieces = [];
          const push = (value) => {
            const clean = String(value || '').replace(/\\s+/g, ' ').trim();
            if (clean && !pieces.includes(clean)) pieces.push(clean);
          };
          const cleanText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
          const usefulPrompt = (value) => {
            const text = cleanText(value);
            if (!text || text.length < 6 || text.length > 500) return '';
            if (!/[A-Za-z]/.test(text)) return '';
            if (/^(?:yes|no|true|false|select|choose|type your response|write here)\\b/i.test(text)) return '';
            return text;
          };

          ['name','id','placeholder','aria-label','autocomplete',
           'data-testid','data-qa','data-automation-id'].forEach(
            (name) => push(el.getAttribute(name))
          );
          if (el.labels) Array.from(el.labels).forEach((label) => push(label.innerText));
          (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));
          (el.getAttribute('aria-describedby') || '').split(/\\s+/).filter(Boolean)
            .forEach((id) => push(document.getElementById(id)?.innerText));

          // Lever hosted forms have used more than one wrapper shape for employer-authored
          // card fields. Prefer the explicit application-question wrapper when present,
          // but do not depend on one class name for safety-critical question retention.
          const applicationQuestion = el.closest(
            '.application-question,[class*="application-question"],' +
            '[data-qa*="application-question"],[data-testid*="application-question"]'
          );
          if (applicationQuestion) {
            const directPrompt = applicationQuestion.querySelector(
              ':scope > label, :scope > legend, :scope > .application-label,' +
              ':scope > [class*="question-label"], :scope > [data-qa*="label"], :scope > [data-testid*="label"]'
            );
            push(directPrompt?.innerText);
            Array.from(applicationQuestion.children || []).forEach((child) => {
              if (child === directPrompt || child.contains(el)) return;
              if (child.querySelector('input,select,textarea,button,[role="radio"],[role="checkbox"],[role="combobox"]')) return;
              const text = usefulPrompt(child.innerText);
              if (text) push(text);
            });
          }

          const group = el.closest('fieldset,[role="radiogroup"],[role="group"]');
          if (group) {
            push(group.getAttribute('aria-label'));
            push(group.querySelector(':scope > legend')?.innerText);
          }
          push(el.closest('label')?.innerText);

          // Current Lever card controls can expose only cards[uuid][fieldN] on the
          // control itself while the human prompt lives in a nearby wrapper. When that
          // opaque identity is present, walk only the nearest few ancestors and retain
          // the first short, control-free human text sibling. This preserves meaning for
          // policy classification without guessing or selecting an answer.
          if (pieces.some((piece) => /^cards\\[[^\\]]+\\]\\[field\\d+\\]$/i.test(piece))) {
            let node = el.parentElement;
            for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
              const directPrompt = node.querySelector(
                ':scope > label, :scope > legend, :scope > .application-label,' +
                ':scope > [class*="question-label"], :scope > [data-qa*="label"], :scope > [data-testid*="label"]'
              );
              const promptText = usefulPrompt(directPrompt?.innerText);
              if (promptText) {
                push(promptText);
                break;
              }

              let found = '';
              for (const child of Array.from(node.children || [])) {
                if (child.contains(el)) continue;
                if (child.querySelector('input,select,textarea,button,[role="radio"],[role="checkbox"],[role="combobox"]')) continue;
                const text = usefulPrompt(child.innerText);
                if (text) {
                  found = text;
                  break;
                }
              }
              if (found) {
                push(found);
                break;
              }
            }
          }

          return pieces.join(' | ');
        }"""
    )
    return re.sub(r"\s+", " ", descriptor or "").strip()
