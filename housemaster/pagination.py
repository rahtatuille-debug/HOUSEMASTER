from rest_framework.pagination import PageNumberPagination


class LongListPagination(PageNumberPagination):
    """
    For lists that grow with time (grades, attendance, conversations and
    their messages): 100 rows a page by default, up to 500 with ?page_size=.
    Responses look like {count, next, previous, results}. Small reference
    lists (subjects, terms, classes...) stay unpaginated.
    """

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500


class PagedOnRequest(LongListPagination):
    """
    The same pages, but only when the client asks for one with ?page= or
    ?page_size=. Without either the whole list comes back as before. For
    lists that the already-deployed frontend reads as plain lists (reports,
    announcements, change requests); once every client asks for pages they
    can move to LongListPagination.
    """

    def paginate_queryset(self, queryset, request, view=None):
        params = request.query_params
        if self.page_query_param not in params and self.page_size_query_param not in params:
            return None
        return super().paginate_queryset(queryset, request, view)
