from . import msgFact as _
from .utils import safe_decode
from .utils import safe_encode
from .vocabularies import GROUPBY_CRITERIA
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.app.contenttypes.behaviors.collection import ISyndicatableCollection
from plone.app.event.base import _prepare_range
from plone.app.event.base import guess_date_from
from plone.app.event.base import start_end_from_mode
from plone.app.event.base import start_end_query
from plone.app.portlets.browser import z3cformhelper
from plone.app.portlets.portlets import base
from plone.app.uuid.utils import uuidToObject
from plone.app.vocabularies.catalog import CatalogSource
from plone.memoize import ram
from plone.memoize.instance import memoize
from plone.portlet.collection.collection import Renderer as CollectionRenderer
from plone.portlets.interfaces import IPortletDataProvider
from time import time
from urllib import urlencode
from z3c.form import field
from zope import schema
from zope.interface import implements

try:
    from plone.app.event.browser.event_listing import EventListing
except ImportError:
    class EventListing(object):
        pass

from datetime import datetime
import logging
logger = logging.getLogger(name="collective.portlet.collectionfilter")


class ICollectionFilterPortlet(IPortletDataProvider):

    header = schema.TextLine(
        title=_('label_header', default=u'Portlet header'),
        description=_(
            'help_header'
            u'Title of the rendered portlet.'
        ),
        required=False,
    )

    target_collection = schema.Choice(
        title=_(u'label_target_collection', default=u'Target Collection'),
        description=_(
            u'help_target_collection',
            default=u'The collection, which is the source for the filter '
                    u'items and where the filter is applied.'
        ),
        required=True,
        source=CatalogSource(
            object_provides=ISyndicatableCollection.__identifier__
        ),
    )

    group_by = schema.Choice(
        title=_('label_groupby', u'Group by'),
        description=_(
            'help_groupby',
            u'Select the criteria to group the collection results by.'
        ),
        required=True,
        vocabulary='collective.portlet.collectionfilter.GroupByCriteria',
    )

    show_count = schema.Bool(
        title=_(u'label_show_count', default=u'Show count'),
        description=_(
            u'help_show_count',
            default=u'Show the result count for each filter group.'),
        default=False,
        required=False
    )

#    faceted = schema.Bool(
#        title=_(u'label_faceted', default=u'Faceted Filter'),
#        description=_(
#            u'help_faceted',
#            default=u'Use faceted filtering by keeping previously selected '
#                    u'criterias active.'),
#        default=False,
#        required=False
#    )

#    faceted_operator = schema.Choice(
#        title=_(
#           u'label_faceted_operator', default=u'Faceted Filter Operator'),
#        description=_(
#            u'help_faceted_operator',
#            default=u'Select, if all (and) or any (or) selected filter '
#                    u'criterias must be met.'),
#        required=True,
#        vocabulary='collective.portlet.collectionfilter.FacetedOperator',
#    )

#    list_scaling = schema.Choice(
#        title=_('label_list_scaling', u'List scaling'),
#        description=_(
#            'help_list_scaling',
#            u'Scale list by count. If a scaling is selected, a the list '
#            u'appears as tagcloud.'
#        ),
#        required=True,
#        vocabulary='collective.portlet.collectionfilter.ListScaling',
#    )


class Assignment(base.Assignment):
    implements(ICollectionFilterPortlet)

    header = u""
    target_collection = None
    group_by = u""
    show_count = False
    # faceted = False
    # faceted_operator = 'and'
    # list_scaling = None

    def __init__(
        self,
        header=u"",
        target_collection=None,
        group_by=u"",
        show_count=False,
        # faceted=False,
        # faceted_operator='and',
        # list_scaling=None
    ):
        self.header = header
        self.target_collection = target_collection
        self.group_by = group_by
        self.show_count = show_count
        # self.faceted = faceted
        # self.faceted_operator = faceted_operator
        # self.list_scaling = list_scaling

    @property
    def title(self):
        if self.header:
            return self.header
        else:
            return _(u'Collection Filter')


def _results_cachekey(method, self, collection, request_params):
    timeout = time() // (60 * 60)  # cache for one hour
    return ('/'.join(collection.getPhysicalPath()), request_params, timeout)


class Renderer(CollectionRenderer):
    render = ViewPageTemplateFile('collectionfilter.pt')

    @property
    def available(self):
        return True

    def header_title(self):
        if self.data.header:
            return self.data.header

        collection = self.collection
        if collection is None:
            return None
        else:
            return collection.Title()

    @property
    @memoize
    def collection(self):
        item = uuidToObject(self.data.target_collection)
        return item

    def results(self):
        t1 = datetime.now()  # LOGGING

        # return cached
        results = self._results(self.collection, self.request.form or {})

        t2 = datetime.now()  # LOGGING
        logger.info("time to build cloud: {0}".format(
            (t2 - t1).total_seconds())
        )
        return results

    @ram.cache(_results_cachekey)
    def _results(self, collection, request_params):
        logger.info("rebuild cloud")
        ret = []
        if collection:
            collection_layout = collection.getLayout()
            default_view = collection.restrictedTraverse(collection_layout)
            results = []
            custom_query = {}
            if isinstance(default_view, EventListing):
                mode = request_params.get('mode', 'future')
                date = request_params.get('date', None)
                date = guess_date_from(date) if date else None

                start, end = start_end_from_mode(mode, date, collection)
                start, end = _prepare_range(collection, start, end)
                custom_query.update(start_end_query(start, end))
                # TODO: expand events. better yet, let collection.results
                #       do that

            idx = GROUPBY_CRITERIA[self.data.group_by]['index']
            urlquery = {}
            urlquery.update(request_params)
            for it in (idx, 'b_start', 'b_size', 'batch', 'sort_on', 'limit'):
                # Remove problematic url parameters
                # And make sure to not filter by previously selected terms from
                # this index. This narrows down too much (except for dedicated
                # facetted searches - TODO)
                if it in urlquery:
                    del urlquery[it]

            custom_query.update(urlquery)
            results = collection.results(
                batch=False, custom_query=custom_query
            )

            if results:

                ret.append(dict(
                    title=_('subject_all', default=u'All categories'),
                    url=u'{0}/?{1}'.format(
                        self.collection.absolute_url(),
                        urlencode(urlquery)
                    ),
                    count=len(results),
                    selected=idx not in request_params
                ))

                attr = GROUPBY_CRITERIA[self.data.group_by]['metadata']
                mod = GROUPBY_CRITERIA[self.data.group_by]['display_modifier']

                grouped_results = {}
                for item in results:
                    val = getattr(item, attr, None)
                    if callable(val):
                        val = val()
                    if not getattr(val, '__iter__', False):
                        val = [val]
                    if not val:
                        # We want to count items with empty criterions too.
                        val = ['']
                    for crit in val:
                        if crit not in grouped_results:
                            crit = crit or ''
                            urlquery[idx] = crit
                            title = safe_decode(mod(crit) if mod else crit) if crit else _('crit_other', default=u'Other')  # modify for displaying (e.g. uuid to title)  # noqa
                            url = u'{0}/?{1}'.format(
                                self.collection.absolute_url(),
                                urlencode(safe_encode(urlquery))  # need to be utf-8 encoded  # noqa
                            )
                            selected = safe_decode(request_params.get(idx)) == safe_decode(crit)  # noqa
                            sort_key = crit if crit else 'zzzzzz'
                            crit_dict = {
                                'sort_key': sort_key.lower(),
                                'count': 1,
                                'title': title,
                                'url': url,
                                'selected': selected
                            }
                            grouped_results[crit] = crit_dict

                        else:
                            grouped_results[crit]['count'] += 1

                ret += sorted(
                    grouped_results.values(),
                    key=lambda it: it['sort_key']
                )

        return ret


class AddForm(z3cformhelper.AddForm):
    fields = field.Fields(ICollectionFilterPortlet)

    label = _(u"Add Collection Filter Portlet")
    description = _(
        u"This portlet shows grouped criteria of collection results and "
        u"allows filtering of collection results."
    )

    def create(self, data):
        return Assignment(**data)


class EditForm(z3cformhelper.EditForm):
    fields = field.Fields(ICollectionFilterPortlet)

    label = _(u"Edit Collection Filter Portlet")
    description = _(
        u"This portlet shows grouped criteria of collection results and "
        u"allows filtering of collection results."
    )
