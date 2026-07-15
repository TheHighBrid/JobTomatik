import re


async def element_descriptor(page, element) -> str:
    descriptor = await element.evaluate(
        """(el) => {
          const pieces = [];
          const push = (value) => {
            const clean = String(value || '').replace(/\\s+/g, ' ').trim();
            if (clean && !pieces.includes(clean)) pieces.push(clean);
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
          const group = el.closest('fieldset,[role="radiogroup"],[role="group"]');
          if (group) {
            push(group.getAttribute('aria-label'));
            push(group.querySelector(':scope > legend')?.innerText);
          }
          push(el.closest('label')?.innerText);
          return pieces.join(' | ');
        }"""
    )
    return re.sub(r"\s+", " ", descriptor or "").strip()
