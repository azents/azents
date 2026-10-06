# azentsadminclient.DebugV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**debug_v1_fire_exception**](DebugV1Api.md#debug_v1_fire_exception) | **POST** /debug/v1/fire-exception | Fire Exception
[**debug_v1_fire_log**](DebugV1Api.md#debug_v1_fire_log) | **POST** /debug/v1/fire-log | Fire Log
[**debug_v1_get_session_diagnostic_events**](DebugV1Api.md#debug_v1_get_session_diagnostic_events) | **GET** /debug/v1/sessions/{session_id}/events | Get Session Diagnostic Events
[**debug_v1_get_session_diagnostic_file**](DebugV1Api.md#debug_v1_get_session_diagnostic_file) | **GET** /debug/v1/sessions/{session_id}/file | Get Session Diagnostic File
[**debug_v1_get_session_diagnostics**](DebugV1Api.md#debug_v1_get_session_diagnostics) | **GET** /debug/v1/sessions/{session_id} | Get Session Diagnostics


# **debug_v1_fire_exception**
> DebugExceptionResponse debug_v1_fire_exception(message=message)

Fire Exception

Raise an unhandled exception.

FastAPI returns 500 and sends an event with stacktrace to Sentry.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.debug_exception_response import DebugExceptionResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.DebugV1Api(api_client)
    message = 'Debug test exception from admin API' # str | Exception message (optional) (default to 'Debug test exception from admin API')

    try:
        # Fire Exception
        api_response = api_instance.debug_v1_fire_exception(message=message)
        print("The response of DebugV1Api->debug_v1_fire_exception:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DebugV1Api->debug_v1_fire_exception: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **message** | **str**| Exception message | [optional] [default to &#39;Debug test exception from admin API&#39;]

### Return type

[**DebugExceptionResponse**](DebugExceptionResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **debug_v1_fire_log**
> DebugErrorResponse debug_v1_fire_log(level=level, message=message)

Fire Log

Emit a log at the specified level.

Used to verify Sentry delivery.
- WARNING: Sentry breadcrumb attached to the next event
- ERROR/CRITICAL: sent directly with ``sentry_sdk.capture_message()``

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.debug_error_response import DebugErrorResponse
from azentsadminclient.models.error_level import ErrorLevel
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.DebugV1Api(api_client)
    level = azentsadminclient.ErrorLevel() # ErrorLevel | Log level (warning, error, critical) (optional)
    message = 'Debug test log from admin API' # str | Log message (optional) (default to 'Debug test log from admin API')

    try:
        # Fire Log
        api_response = api_instance.debug_v1_fire_log(level=level, message=message)
        print("The response of DebugV1Api->debug_v1_fire_log:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DebugV1Api->debug_v1_fire_log: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **level** | [**ErrorLevel**](.md)| Log level (warning, error, critical) | [optional] 
 **message** | **str**| Log message | [optional] [default to &#39;Debug test log from admin API&#39;]

### Return type

[**DebugErrorResponse**](DebugErrorResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **debug_v1_get_session_diagnostic_events**
> SessionDiagnosticEventPage debug_v1_get_session_diagnostic_events(session_id, workspace_id, after=after, limit=limit)

Get Session Diagnostic Events

Page safe canonical audit records without exposing native model artifacts.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.session_diagnostic_event_page import SessionDiagnosticEventPage
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.DebugV1Api(api_client)
    session_id = 'session_id_example' # str | 
    workspace_id = 'workspace_id_example' # str | 
    after = 'after_example' # str |  (optional)
    limit = 20 # int |  (optional) (default to 20)

    try:
        # Get Session Diagnostic Events
        api_response = api_instance.debug_v1_get_session_diagnostic_events(session_id, workspace_id, after=after, limit=limit)
        print("The response of DebugV1Api->debug_v1_get_session_diagnostic_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DebugV1Api->debug_v1_get_session_diagnostic_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  | 
 **workspace_id** | **str**|  | 
 **after** | **str**|  | [optional] 
 **limit** | **int**|  | [optional] [default to 20]

### Return type

[**SessionDiagnosticEventPage**](SessionDiagnosticEventPage.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **debug_v1_get_session_diagnostic_file**
> SessionDiagnosticFile debug_v1_get_session_diagnostic_file(session_id, workspace_id, path, offset=offset, limit=limit)

Get Session Diagnostic File

Read retained current file content without file versions or restoration.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.session_diagnostic_file import SessionDiagnosticFile
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.DebugV1Api(api_client)
    session_id = 'session_id_example' # str | 
    workspace_id = 'workspace_id_example' # str | 
    path = 'path_example' # str | 
    offset = 0 # int |  (optional) (default to 0)
    limit = 10000 # int |  (optional) (default to 10000)

    try:
        # Get Session Diagnostic File
        api_response = api_instance.debug_v1_get_session_diagnostic_file(session_id, workspace_id, path, offset=offset, limit=limit)
        print("The response of DebugV1Api->debug_v1_get_session_diagnostic_file:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DebugV1Api->debug_v1_get_session_diagnostic_file: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  | 
 **workspace_id** | **str**|  | 
 **path** | **str**|  | 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 10000]

### Return type

[**SessionDiagnosticFile**](SessionDiagnosticFile.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **debug_v1_get_session_diagnostics**
> SessionDiagnosticMetadata debug_v1_get_session_diagnostics(session_id, workspace_id)

Get Session Diagnostics

Inspect retained common metadata under authenticated operational authority.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.session_diagnostic_metadata import SessionDiagnosticMetadata
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.DebugV1Api(api_client)
    session_id = 'session_id_example' # str | 
    workspace_id = 'workspace_id_example' # str | 

    try:
        # Get Session Diagnostics
        api_response = api_instance.debug_v1_get_session_diagnostics(session_id, workspace_id)
        print("The response of DebugV1Api->debug_v1_get_session_diagnostics:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DebugV1Api->debug_v1_get_session_diagnostics: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **session_id** | **str**|  | 
 **workspace_id** | **str**|  | 

### Return type

[**SessionDiagnosticMetadata**](SessionDiagnosticMetadata.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

