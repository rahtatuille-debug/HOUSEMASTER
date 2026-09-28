from rest_framework.pagination import PageNumberPagination


class LongListPagination(PageNumberPagination):
    """
    For lists that grow with time (grades, attendance, conversation
    messages): 100 rows a page by default, up to 500 with ?page_size=.
    Responses look like {count, next, previous, results}. Small reference
    lists (subjects, terms, classes...) stay unpaginated.
    """

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500
