# azentspublicclient.PersonalGoogleToolkitV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**personal_google_toolkit_v1_personal_google_cancel**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_cancel) | **DELETE** /toolkit/v1/workspaces/{handle}/personal/google/attempts/{attempt_id} | Personal Google Cancel
[**personal_google_toolkit_v1_personal_google_confirm**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_confirm) | **POST** /toolkit/v1/workspaces/{handle}/personal/google/attempts/{attempt_id}/confirm | Personal Google Confirm
[**personal_google_toolkit_v1_personal_google_connect**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_connect) | **POST** /toolkit/v1/workspaces/{handle}/personal/google/connect | Personal Google Connect
[**personal_google_toolkit_v1_personal_google_disconnect**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_disconnect) | **DELETE** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/google/connection | Personal Google Disconnect
[**personal_google_toolkit_v1_personal_google_exchange**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_exchange) | **POST** /toolkit/v1/workspaces/{handle}/personal/google/exchange | Personal Google Exchange
[**personal_google_toolkit_v1_personal_google_outcome**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_outcome) | **GET** /toolkit/v1/workspaces/{handle}/personal/google/attempts/{attempt_id}/outcome | Personal Google Outcome
[**personal_google_toolkit_v1_personal_google_preparation**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_preparation) | **GET** /toolkit/v1/workspaces/{handle}/personal/google/preparation | Personal Google Preparation
[**personal_google_toolkit_v1_personal_google_reconnect**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_reconnect) | **POST** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/google/reconnect | Personal Google Reconnect
[**personal_google_toolkit_v1_personal_google_reconnect_confirm**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_reconnect_confirm) | **POST** /toolkit/v1/workspaces/{handle}/personal/google/attempts/{attempt_id}/reconnect-confirm | Personal Google Reconnect Confirm
[**personal_google_toolkit_v1_personal_google_review**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_review) | **GET** /toolkit/v1/workspaces/{handle}/personal/google/attempts/{attempt_id} | Personal Google Review
[**personal_google_toolkit_v1_personal_google_status**](PersonalGoogleToolkitV1Api.md#personal_google_toolkit_v1_personal_google_status) | **GET** /toolkit/v1/workspaces/{handle}/personal-toolkit-configs/{toolkit_id}/google/connection | Personal Google Status


# **personal_google_toolkit_v1_personal_google_cancel**
> GoogleCancelOutput personal_google_toolkit_v1_personal_google_cancel(attempt_id, handle)

Personal Google Cancel

Abandon unpublished secrets while retaining committed publication evidence.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_cancel_output import GoogleCancelOutput
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Google Cancel
        api_response = api_instance.personal_google_toolkit_v1_personal_google_cancel(attempt_id, handle)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_cancel:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_cancel: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleCancelOutput**](GoogleCancelOutput.md)

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

# **personal_google_toolkit_v1_personal_google_confirm**
> GooglePublishedOutput personal_google_toolkit_v1_personal_google_confirm(attempt_id, handle, google_confirm_request)

Personal Google Confirm

Publish a canonical User-owned Toolkit after reviewed confirmation.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_confirm_request import GoogleConfirmRequest
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 
    google_confirm_request = azentspublicclient.GoogleConfirmRequest() # GoogleConfirmRequest | 

    try:
        # Personal Google Confirm
        api_response = api_instance.personal_google_toolkit_v1_personal_google_confirm(attempt_id, handle, google_confirm_request)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_confirm_request** | [**GoogleConfirmRequest**](GoogleConfirmRequest.md)|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_google_toolkit_v1_personal_google_connect**
> GoogleConnectOutput personal_google_toolkit_v1_personal_google_connect(handle, google_connect_input)

Personal Google Connect

Stage a personal setup without publishing a Toolkit or credential.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connect_input import GoogleConnectInput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    google_connect_input = azentspublicclient.GoogleConnectInput() # GoogleConnectInput | 

    try:
        # Personal Google Connect
        api_response = api_instance.personal_google_toolkit_v1_personal_google_connect(handle, google_connect_input)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_connect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_connect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **google_connect_input** | [**GoogleConnectInput**](GoogleConnectInput.md)|  | 

### Return type

[**GoogleConnectOutput**](GoogleConnectOutput.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_google_toolkit_v1_personal_google_disconnect**
> object personal_google_toolkit_v1_personal_google_disconnect(toolkit_id, handle)

Personal Google Disconnect

Delete personal Google credentials and defeat pending stale reconnects.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Google Disconnect
        api_response = api_instance.personal_google_toolkit_v1_personal_google_disconnect(toolkit_id, handle)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_disconnect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_disconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

**object**

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

# **personal_google_toolkit_v1_personal_google_exchange**
> GoogleReview personal_google_toolkit_v1_personal_google_exchange(handle, google_exchange_request)

Personal Google Exchange

Verify exact personal callback state before exchanging or staging credentials.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_exchange_request import GoogleExchangeRequest
from azentspublicclient.models.google_review import GoogleReview
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    handle = 'handle_example' # str | 
    google_exchange_request = azentspublicclient.GoogleExchangeRequest() # GoogleExchangeRequest | 

    try:
        # Personal Google Exchange
        api_response = api_instance.personal_google_toolkit_v1_personal_google_exchange(handle, google_exchange_request)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_exchange:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_exchange: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **google_exchange_request** | [**GoogleExchangeRequest**](GoogleExchangeRequest.md)|  | 

### Return type

[**GoogleReview**](GoogleReview.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_google_toolkit_v1_personal_google_outcome**
> GooglePublishedOutput personal_google_toolkit_v1_personal_google_outcome(attempt_id, handle)

Personal Google Outcome

Recover uncertain publication under its exact original owner context.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Google Outcome
        api_response = api_instance.personal_google_toolkit_v1_personal_google_outcome(attempt_id, handle)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_outcome:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_outcome: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

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

# **personal_google_toolkit_v1_personal_google_preparation**
> GooglePreparation personal_google_toolkit_v1_personal_google_preparation(handle)

Personal Google Preparation

Expose common operator registration readiness to the exact active account.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_preparation import GooglePreparation
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Personal Google Preparation
        api_response = api_instance.personal_google_toolkit_v1_personal_google_preparation(handle)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_preparation:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_preparation: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GooglePreparation**](GooglePreparation.md)

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

# **personal_google_toolkit_v1_personal_google_reconnect**
> GoogleConnectOutput personal_google_toolkit_v1_personal_google_reconnect(toolkit_id, handle, google_connect_input)

Personal Google Reconnect

Reconnect the exact User-owned target with common reviewed identity flow.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connect_input import GoogleConnectInput
from azentspublicclient.models.google_connect_output import GoogleConnectOutput
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 
    google_connect_input = azentspublicclient.GoogleConnectInput() # GoogleConnectInput | 

    try:
        # Personal Google Reconnect
        api_response = api_instance.personal_google_toolkit_v1_personal_google_reconnect(toolkit_id, handle, google_connect_input)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_reconnect:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_reconnect: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_connect_input** | [**GoogleConnectInput**](GoogleConnectInput.md)|  | 

### Return type

[**GoogleConnectOutput**](GoogleConnectOutput.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_google_toolkit_v1_personal_google_reconnect_confirm**
> GooglePublishedOutput personal_google_toolkit_v1_personal_google_reconnect_confirm(attempt_id, handle, google_reconnect_confirm_request)

Personal Google Reconnect Confirm

Replace the grant while preserving personal allowance and other settings.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_published_output import GooglePublishedOutput
from azentspublicclient.models.google_reconnect_confirm_request import GoogleReconnectConfirmRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 
    google_reconnect_confirm_request = azentspublicclient.GoogleReconnectConfirmRequest() # GoogleReconnectConfirmRequest | 

    try:
        # Personal Google Reconnect Confirm
        api_response = api_instance.personal_google_toolkit_v1_personal_google_reconnect_confirm(attempt_id, handle, google_reconnect_confirm_request)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_reconnect_confirm:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_reconnect_confirm: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 
 **google_reconnect_confirm_request** | [**GoogleReconnectConfirmRequest**](GoogleReconnectConfirmRequest.md)|  | 

### Return type

[**GooglePublishedOutput**](GooglePublishedOutput.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_google_toolkit_v1_personal_google_review**
> GoogleReview personal_google_toolkit_v1_personal_google_review(attempt_id, handle)

Personal Google Review

Review verified grant evidence without exposing candidate credentials.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_review import GoogleReview
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    attempt_id = 'attempt_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Google Review
        api_response = api_instance.personal_google_toolkit_v1_personal_google_review(attempt_id, handle)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_review:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_review: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **attempt_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleReview**](GoogleReview.md)

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

# **personal_google_toolkit_v1_personal_google_status**
> GoogleConnectionOutput personal_google_toolkit_v1_personal_google_status(toolkit_id, handle)

Personal Google Status

Return the same redacted grant/readiness information as other owners.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.PersonalGoogleToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    handle = 'handle_example' # str | 

    try:
        # Personal Google Status
        api_response = api_instance.personal_google_toolkit_v1_personal_google_status(toolkit_id, handle)
        print("The response of PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalGoogleToolkitV1Api->personal_google_toolkit_v1_personal_google_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **handle** | **str**|  | 

### Return type

[**GoogleConnectionOutput**](GoogleConnectionOutput.md)

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

