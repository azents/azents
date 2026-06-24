# azentsadminclient.DebugV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**debug_v1_fire_exception**](DebugV1Api.md#debug_v1_fire_exception) | **POST** /debug/v1/fire-exception | Fire Exception
[**debug_v1_fire_log**](DebugV1Api.md#debug_v1_fire_log) | **POST** /debug/v1/fire-log | Fire Log


# **debug_v1_fire_exception**
> DebugExceptionResponse debug_v1_fire_exception(message=message)

Fire Exception

Raise an unhandled exception.

FastAPI returns 500 and sends an event with stacktrace to Sentry.

### Example


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

No authorization required

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

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)
