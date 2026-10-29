from odoo.addons.portal.controllers.portal import pager

# Rows per page on every portal list. Keep a single value so all listing
# pages paginate the same way.
PORTAL_PAGE_STEP = 10


def paginate(records_model, domain, url, page, url_args=None, order=None,
             step=PORTAL_PAGE_STEP):
    """Shared pagination for portal lists.

    Counts the records matching ``domain``, builds the standard portal
    pager for ``url`` and fetches only the current page. Returns
    ``(records, total, pager_dict)``.
    """
    total = records_model.search_count(domain)
    page_detail = pager(
        url=url,
        total=total,
        page=page,
        step=step,
        url_args=url_args or None,
    )
    _pager_add_summary(page_detail, total, step)
    records = records_model.search(
        domain, limit=step, offset=page_detail['offset'], order=order,
    )
    return records, total, page_detail


def _pager_add_summary(page_detail, total, step):
    """Extra keys consumed by the shared `portal_list_pager` template to
    render the "Showing X-Y of Z" summary (core `portal.pager` only
    renders page links, and only when there is more than one page)."""
    page_detail.update({
        'total': total,
        'range_start': page_detail['offset'] + 1 if total else 0,
        'range_end': min(page_detail['offset'] + step, total),
    })
