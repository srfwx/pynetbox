"""
(c) 2017 DigitalOcean

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import marshal
from urllib.parse import urlsplit

from pynetbox.core.query import Request
from pynetbox.core.util import Hashabledict

# List of fields that are lists but should be treated as sets.
LIST_AS_SET = ("tags", "tagged_vlans")


def flatten_custom(custom_dict):
    ret = {}

    for k, val in custom_dict.items():
        current_val = val

        if isinstance(val, dict):
            current_val = val.get("id", val)

        if isinstance(val, list):
            current_val = [v.get("id", v) if isinstance(v, dict) else v for v in val]

        ret[k] = current_val
    return ret


class JsonField:
    """Explicit field type for values that are not to be converted
    to a Record object."""

    _json_field = True


class RecordSet:
    """Iterator containing Record objects.

    Returned by `Endpoint.all()` and `Endpoint.filter()` methods.
    Allows iteration of and actions to be taken on the results from the aforementioned
    methods. Contains Record objects.

    ## Examples

    To see how many results are in a query by calling `len()`:

    ```python
    x = nb.dcim.devices.all()
    len(x)
    # 123
    ```

    Simple iteration of the results:

    ```python
    devices = nb.dcim.devices.all()
    for device in devices:
        print(device.name)

    # test1-leaf1
    # test1-leaf2
    # test1-leaf3
    ```
    """

    def __init__(self, endpoint, request, **kwargs):
        self.endpoint = endpoint
        self.request = request
        self.response = self.request.get()
        self._response_cache = []

    def __iter__(self):
        return self

    def __next__(self):
        if self._response_cache:
            return self.endpoint.return_obj(
                self._response_cache.pop(),
                self.endpoint.api,
                self.endpoint,
            )
        return self.endpoint.return_obj(
            next(self.response),
            self.endpoint.api,
            self.endpoint,
        )

    def __len__(self):
        try:
            return self.request.count
        except AttributeError:
            try:
                self._response_cache.append(next(self.response))
            except StopIteration:
                return 0
            return self.request.count

    def update(self, **kwargs):
        """Updates kwargs onto all Records in the RecordSet and saves these.

        Updates are only sent to the API if a value were changed, and only for
        the Records which were changed.

        ## Returns
        True if the update succeeded, None if no update were required.

        ## Examples

        ```python
        result = nb.dcim.devices.filter(site_id=1).update(status='active')
        # True
        ```
        """
        updates = []
        for record in self:
            # Update each record and determine if anything was updated
            for k, v in kwargs.items():
                setattr(record, k, v)
            record_updates = record.updates()
            if record_updates:
                # if updated, add the id to the dict and append to list of updates
                record_updates["id"] = record.id
                updates.append(record_updates)
        if updates:
            return self.endpoint.update(updates)
        else:
            return None

    def delete(self):
        """Bulk deletes objects in a RecordSet.

        Allows for batch deletion of multiple objects in a RecordSet.

        ## Returns
        True if bulk DELETE operation was successful.

        ## Examples

        Deleting offline `devices` on site 1:

        ```python
        netbox.dcim.devices.filter(site_id=1, status="offline").delete()
        ```
        """
        return self.endpoint.delete(self)


class BaseRecord:
    def __init__(self):
        self._init_cache = []

    def __getitem__(self, k):
        return dict(self)[k]

    def __repr__(self):
        return str(self)

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, d):
        self.__dict__.update(d)


class ValueRecord(BaseRecord):
    def __init__(self, values, *args, **kwargs):
        super().__init__()
        if values:
            self._parse_values(values)

    def __iter__(self):
        for k, _ in self._init_cache:
            cur_attr = getattr(self, k)
            yield k, cur_attr

    def __repr__(self):
        return getattr(self, "label", "")

    @property
    def _key(self):
        return getattr(self, "value")

    def __eq__(self, other):
        if isinstance(other, ValueRecord):
            return self._foreign_key == other._foreign_key
        return NotImplemented

    def _parse_values(self, values):
        for k, v in values.items():
            self._init_cache.append((k, v))
            setattr(self, k, v)

    def serialize(self, nested=False):
        return self._key if nested else dict(self)


class Record(BaseRecord):
    """Create Python objects from NetBox API responses.

    Creates an object from a NetBox response passed as `values`.
    Nested dicts that represent other endpoints are also turned
    into Record objects. All fields are then assigned to the
    object's attributes. If a missing attr is requested
    (e.g. requesting a field that's only present on a full response on
    a Record made from a nested response) then pynetbox will make a
    request for the full object and return the requested value.

    ## Examples

    Default representation of the object is usually its name:

    ```python
    x = nb.dcim.devices.get(1)
    x
    # test1-switch1
    ```

    Querying a string field:

    ```python
    x = nb.dcim.devices.get(1)
    x.serial
    # 'ABC123'
    ```

    Querying a field on a nested object:

    ```python
    x = nb.dcim.devices.get(1)
    x.device_type.model
    # 'QFX5100-24Q'
    ```

    Casting the object as a dictionary:

    ```python
    from pprint import pprint
    pprint(dict(x))
    {
        'asset_tag': None,
        'cluster': None,
        'comments': '',
        'config_context': {},
        'created': '2018-04-01',
        'custom_fields': {},
        'role': {
            'id': 1,
            'name': 'Test Switch',
            'slug': 'test-switch',
            'url': 'http://localhost:8000/api/dcim/device-roles/1/'
        },
        'device_type': {...},
        'display_name': 'test1-switch1',
        'face': {'label': 'Rear', 'value': 1},
        'id': 1,
        'name': 'test1-switch1',
        'parent_device': None,
        'platform': {...},
        'position': 1,
        'primary_ip': {
            'address': '192.0.2.1/24',
            'family': 4,
            'id': 1,
            'url': 'http://localhost:8000/api/ipam/ip-addresses/1/'
        },
        'primary_ip4': {...},
        'primary_ip6': None,
        'rack': {
            'display_name': 'Test Rack',
            'id': 1,
            'name': 'Test Rack',
            'url': 'http://localhost:8000/api/dcim/racks/1/'
        },
        'site': {
            'id': 1,
            'name': 'TEST',
            'slug': 'TEST',
            'url': 'http://localhost:8000/api/dcim/sites/1/'
        },
        'status': {'label': 'Active', 'value': 1},
        'tags': [],
        'tenant': None,
        'vc_position': None,
        'vc_priority': None,
        'virtual_chassis': None
    }
    ```

    Iterating over a Record object:

    ```python
    for i in x:
        print(i)

    # ('id', 1)
    # ('name', 'test1-switch1')
    # ('display_name', 'test1-switch1')
    ```
    """

    url = None

    # Internal Record metadata that should not be serialized for API updates.
    # These are object bookkeeping attributes, not NetBox API fields.
    _INTERNAL_ATTRS = frozenset(
        [
            "api",  # API client instance
            "endpoint",  # Endpoint object reference
            "url",  # Object URL (read-only field provided by API)
            "has_details",  # Flag for lazy-loading full details
            "default_ret",  # Default Record class for nested objects
        ]
    )

    def __init__(self, values, api, endpoint):
        self.has_details = False
        super().__init__()
        self.api = api
        self.default_ret = Record
        self.url = values.get("url", None) if values else None
        self._endpoint = endpoint
        if values:
            self._parse_values(values)

    def __getattr__(self, k):
        """Default behavior for missing attrs.

        We'll call `full_details()` if we're asked for an attribute
        we don't have.

        In order to prevent non-explicit behavior,`k='keys'` is
        excluded because casting to dict() calls this attr.
        """
        if self.url:
            if self.has_details is False and k != "keys":
                if self.full_details():
                    ret = getattr(self, k, None)
                    if ret or hasattr(self, k):
                        return ret

        raise AttributeError('object has no attribute "{}"'.format(k))

    def __iter__(self):
        for k, _ in self._init_cache:
            cur_attr = getattr(self, k)
            if isinstance(cur_attr, BaseRecord):
                yield k, dict(cur_attr)
            elif isinstance(cur_attr, list) and all(
                isinstance(i, (BaseRecord, GenericListObject)) for i in cur_attr
            ):
                yield k, [dict(x) for x in cur_attr]
            else:
                yield k, cur_attr

    def __str__(self):
        return (
            getattr(self, "name", None)
            or getattr(self, "label", None)
            or getattr(self, "display", None)
            or ""
        )

    def __key__(self):
        if hasattr(self, "id"):
            return (self.endpoint.name, self.id)
        else:
            return self.endpoint.name

    def __hash__(self):
        return hash(self.__key__())

    def __eq__(self, other):
        if isinstance(other, Record):
            return self.__key__() == other.__key__()
        return NotImplemented

    @property
    def endpoint(self):
        if self._endpoint is None:
            self._endpoint = self._endpoint_from_url()
        return self._endpoint

    def _endpoint_from_url(self):
        url_path = self.url.replace(self.api.base_url, "").split("/")
        is_plugin = url_path and url_path[1] == "plugins"
        start = 2 if is_plugin else 1
        app, name = [i.replace("-", "_") for i in url_path[start : start + 2]]
        if is_plugin:
            return getattr(getattr(self.api.plugins, app), name)
        else:
            return getattr(getattr(self.api, app), name)

    def _get_or_init(self, object_type, key, value, model):
        """
        Returns a record from the endpoint cache if it exists, otherwise
        initializes a new record, store it in the cache, and return it.
        """
        if self._endpoint:
            if cached := self._endpoint._cache.get(object_type, key):
                return cached
        record = model(value, self.api, None)
        if self._endpoint:
            self._endpoint._cache.set(object_type, key, record)
        return record

    def _extract_app_endpoint(self, url):
        """Extract app/endpoint from a NetBox API URL.

        Extracts the app and endpoint portion from a URL like:
            https://netbox/api/dcim/rear-ports/12761/
        Returns:
            String like "dcim/rear-ports"
        """
        app_endpoint = "/".join(
            urlsplit(url).path[len(urlsplit(self.api.base_url).path) :].split("/")[1:3]
        )
        return app_endpoint

    def _get_obj_class(self, url):
        """Map API URL to corresponding Record class for cable tracing.

        Used by TraceableRecord and PathableRecord to deserialize objects
        encountered in cable trace/path responses.
        """
        # Import here to avoid circular dependency
        from pynetbox.models.circuits import CircuitTerminations
        from pynetbox.models.dcim import (
            Cables,
            ConsolePorts,
            ConsoleServerPorts,
            FrontPorts,
            Interfaces,
            PowerFeeds,
            PowerOutlets,
            PowerPorts,
            RearPorts,
        )

        uri_to_obj_class_map = {
            "circuits/circuit-terminations": CircuitTerminations,
            "dcim/cables": Cables,
            "dcim/console-ports": ConsolePorts,
            "dcim/console-server-ports": ConsoleServerPorts,
            "dcim/front-ports": FrontPorts,
            "dcim/interfaces": Interfaces,
            "dcim/power-feeds": PowerFeeds,
            "dcim/power-outlets": PowerOutlets,
            "dcim/power-ports": PowerPorts,
            "dcim/rear-ports": RearPorts,
        }

        app_endpoint = self._extract_app_endpoint(url)
        return uri_to_obj_class_map.get(app_endpoint, Record)

    def _parse_values(self, values):
        """Parses values init arg.

        Parses values dict at init and sets object attributes with the
        values within.
        """

        non_record_dict_fields = ["custom_fields", "local_context_data"]

        def deep_copy(value):
            return marshal.loads(marshal.dumps(value))

        def dict_parser(key_name, value, model=None):
            if key_name in non_record_dict_fields:
                return value, deep_copy(value)

            if model is None:
                model = getattr(self.__class__, key_name, None)

            if model and issubclass(model, JsonField):
                return value, deep_copy(value)

            if (id := value.get("id", None)) and (url := value.get("url", None)):
                model = model or Record
                value = self._get_or_init(key_name, url, value, model)
                return value, id

            if record_value := value.get("value", None):
                value = self._get_or_init(key_name, record_value, value, ValueRecord)
                return value, record_value

            return value, deep_copy(value)

        def generic_list_parser(value):
            from pynetbox.models.mapper import CONTENT_TYPE_MAPPER

            parsed_list = []
            for item in value:
                object_type = item["object_type"]
                if model := CONTENT_TYPE_MAPPER.get(object_type, None):
                    item = self._get_or_init(
                        object_type, item["object"]["url"], item["object"], model
                    )
                parsed_list.append(GenericListObject(item))
            return parsed_list

        def list_parser(key_name, value):
            if not value:
                return [], []

            if key_name in ["constraints"]:
                return value, deep_copy(value)

            sample_item = value[0]
            if not isinstance(sample_item, dict):
                return value, [*value]

            is_generic_list = "object_type" in sample_item and "object" in sample_item
            if is_generic_list:
                value = generic_list_parser(value)
            else:
                lookup = getattr(self.__class__, key_name, None)
                model = lookup[0] if isinstance(lookup, list) else self.default_ret
                value = [dict_parser(key_name, i, model=model)[0] for i in value]

            return value, [*value]

        def parse_value(key_name, value):
            if isinstance(value, dict):
                value, to_cache = dict_parser(key_name, value)
            elif isinstance(value, list):
                value, to_cache = list_parser(key_name, value)
            else:
                to_cache = value
            setattr(self, key_name, value)
            return to_cache

        self._init_cache = [(k, parse_value(k, v)) for k, v in values.items()]

    def full_details(self):
        """Queries the hyperlinked endpoint if 'url' is defined.

        This method will populate the attributes from the detail
        endpoint when it's called. Sets the class-level `has_details`
        attribute when it's called to prevent being called more
        than once.

        :returns: True
        """
        if self.url:
            req = Request(
                base=self.url,
                token=self.api.token,
                http_session=self.api.http_session,
            )
            self._parse_values(next(req.get()))
            self.has_details = True
            return True
        return False

    def serialize(self, nested=False, init=False):
        """Serializes an object

        Pulls all the attributes in an object and creates a dict that
        can be turned into the json that netbox is expecting.

        If an attribute's value is a ``Record`` type it's replaced with
        the ``id`` field of that object.

        When ``init=False`` (default), includes both original fields from the
        API response and any fields that have been set on the object after
        initialization. This allows proper change detection for fields set
        to None or other values.

        When ``init=True``, returns only the original fields from the initial
        API response, used for comparing against the current state to detect
        changes.

        .. note::

            Using this to get a dictionary representation of the record
            is discouraged. It's probably better to cast to dict()
            instead. See Record docstring for example.

        :returns: dict.
        """
        if nested:
            return getattr(self, "id")

        # Determine which fields to serialize
        if init:
            # For initial state, use only _init_cache
            init_cache_dict = dict(self._init_cache)
            fields_to_serialize = init_cache_dict.keys()
            init_vals = init_cache_dict
        else:
            # For current state, include all fields (original + modified)
            init_cache_keys = {k for k, _ in self._init_cache}

            # Get all non-internal field names from object's __dict__
            obj_keys = {
                k
                for k in self.__dict__.keys()
                if not k.startswith("_") and k not in self._INTERNAL_ATTRS
            }

            # Combine both sets
            fields_to_serialize = init_cache_keys | obj_keys
            init_vals = {}  # Not used when init=False

        ret = {}

        for i in fields_to_serialize:
            current_val = getattr(self, i, None) if not init else init_vals.get(i)
            if i == "custom_fields":
                ret[i] = flatten_custom(current_val)
            else:
                if isinstance(current_val, BaseRecord):
                    current_val = getattr(current_val, "serialize")(nested=True)

                if isinstance(current_val, list):
                    serialized_list = []
                    for v in current_val:
                        if isinstance(v, GenericListObject):
                            v = v.serialize()
                        elif isinstance(v, BaseRecord):
                            v = v.id
                        serialized_list.append(v)
                    current_val = serialized_list
                    if i in LIST_AS_SET and (
                        all([isinstance(v, str) for v in current_val])
                        or all([isinstance(v, int) for v in current_val])
                    ):
                        current_val = list(dict.fromkeys(current_val))
                ret[i] = current_val

        return ret

    def _diff(self):
        def fmt_dict(k, v):
            if isinstance(v, dict):
                return k, Hashabledict(v)
            if isinstance(v, list):
                return k, ",".join(map(str, v))
            return k, v

        current = Hashabledict({fmt_dict(k, v) for k, v in self.serialize().items()})
        init = Hashabledict(
            {fmt_dict(k, v) for k, v in self.serialize(init=True).items()}
        )
        return set([i[0] for i in set(current.items()) ^ set(init.items())])

    def updates(self):
        """Compiles changes for an existing object into a dict.

        Takes a diff between the objects current state and its state at init
        and returns them as a dictionary, which will be empty if no changes.

        :returns: dict.
        :example:

        >>> x = nb.dcim.devices.get(name='test1-a3-tor1b')
        >>> x.serial
        ''
        >>> x.serial = '1234'
        >>> x.updates()
        {'serial': '1234'}
        >>>
        """
        if self.id:
            diff = self._diff()
            if diff:
                serialized = self.serialize()
                return {i: serialized[i] for i in diff}
        return {}

    def save(self):
        """Saves changes to an existing object.

        Takes a diff between the objects current state and its state at init
        and sends them as a dictionary to Request.patch().

        :returns: True if PATCH request was successful.
        :example:

        >>> x = nb.dcim.devices.get(name='test1-a3-tor1b')
        >>> x.serial
        ''
        >>> x.serial = '1234'
        >>> x.save()
        True
        >>>
        """
        updates = self.updates()
        if updates:
            req = Request(
                key=self.id,
                base=self.endpoint.url,
                token=self.api.token,
                http_session=self.api.http_session,
            )
            result = req.patch(updates)
            if result:
                # Update object state with response from PATCH to keep cache in sync
                self._parse_values(result)
                return True
        return False

    def update(self, data):
        """Update an object with a dictionary.

        Accepts a dict and uses it to update the record and call save().
        For nested and choice fields you'd pass an int the same as
        if you were modifying the attribute and calling save().

        :arg dict data: Dictionary containing the k/v to update the
            record object with.
        :returns: True if PATCH request was successful.
        :example:

        >>> x = nb.dcim.devices.get(1)
        >>> x.update({
        ...   "name": "test-switch2",
        ...   "serial": "ABC321",
        ... })
        True

        """

        for k, v in data.items():
            setattr(self, k, v)
        return self.save()

    def delete(self):
        """Deletes an existing object.

        :returns: True if DELETE operation was successful.
        :example:

        >>> x = nb.dcim.devices.get(name='test1-a3-tor1b')
        >>> x.delete()
        True
        >>>
        """
        req = Request(
            key=self.id,
            base=self.endpoint.url,
            token=self.api.token,
            http_session=self.api.http_session,
        )
        return True if req.delete() else False


class PathableRecord(Record):
    """Record class for objects that support cable path tracing via /paths endpoint.

    Front ports, rear ports, and circuit terminations use the /paths endpoint
    to show complete cable paths from origin to destination.
    """

    def _build_endpoint_object(self, endpoint_data):
        if not endpoint_data:
            return None

        return_obj_class = self._get_obj_class(endpoint_data["url"])
        return return_obj_class(endpoint_data, self.endpoint.api, self.endpoint)

    def paths(self):
        """Return all cable paths traversing this pass-through port.

        Returns a list of dictionaries, each containing:
        - origin: The starting endpoint of the path (or None if not connected)
        - destination: The ending endpoint of the path (or None if not connected)
        - path: List of path segments, where each segment is a list of Record objects
                (similar to the trace() endpoint structure)
        """
        req = Request(
            key=str(self.id) + "/paths",
            base=self.endpoint.url,
            token=self.api.token,
            http_session=self.api.http_session,
        ).get()

        ret = []
        for path_data in req:
            path_segments = []
            for segment_data in path_data.get("path", []):
                segment_objects = []
                if isinstance(segment_data, list):
                    for item_data in segment_data:
                        segment_obj = self._build_endpoint_object(item_data)
                        if segment_obj:
                            segment_objects.append(segment_obj)
                else:
                    segment_obj = self._build_endpoint_object(segment_data)
                    if segment_obj:
                        segment_objects.append(segment_obj)
                path_segments.append(segment_objects)

            origin = self._build_endpoint_object(path_data.get("origin"))
            destination = self._build_endpoint_object(path_data.get("destination"))

            ret.append({
                "origin": origin,
                "destination": destination,
                "path": path_segments,
            })

        return ret


class GenericListObject:
    def __init__(self, record):
        from pynetbox.models.mapper import TYPE_CONTENT_MAPPER

        self.object = record
        self.object_id = record.id
        self.object_type = TYPE_CONTENT_MAPPER.get(record.__class__)

    def __repr__(self):
        return str(self.object)

    def serialize(self):
        ret = {k: getattr(self, k) for k in ["object_id", "object_type"]}
        return ret

    def __getattr__(self, k):
        return getattr(self.object, k)

    def __iter__(self):
        for i in ["object_id", "object_type", "object"]:
            cur_attr = getattr(self, i)
            if isinstance(cur_attr, Record):
                cur_attr = dict(cur_attr)
            yield i, cur_attr
