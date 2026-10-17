# azentspublicclient.PersonalToolkitOAuthV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**personal_toolkit_oauth_v1_connect_personal_oauth**](PersonalToolkitOAuthV1Api.md#personal_toolkit_oauth_v1_connect_personal_oauth) | **POST** /toolkit/v1/personal-toolkit-configs/{toolkit_id}/oauth/connect | Connect Personal Oauth
[**personal_toolkit_oauth_v1_disconnect_personal_oauth**](PersonalToolkitOAuthV1Api.md#personal_toolkit_oauth_v1_disconnect_personal_oauth) | **DELETE** /toolkit/v1/personal-toolkit-configs/{toolkit_id}/oauth | Disconnect Personal Oauth
[**personal_toolkit_oauth_v1_exchange_personal_oauth**](PersonalToolkitOAuthV1Api.md#personal_toolkit_oauth_v1_exchange_personal_oauth) | **POST** /toolkit/v1/personal-toolkit-configs/{toolkit_id}/oauth/exchange | Exchange Personal Oauth
[**personal_toolkit_oauth_v1_test_personal_connection**](PersonalToolkitOAuthV1Api.md#personal_toolkit_oauth_v1_test_personal_connection) | **POST** /toolkit/v1/personal-toolkit-configs/test-connection | Test Personal Connection
[**personal_toolkit_oauth_v1_test_saved_personal_connection**](PersonalToolkitOAuthV1Api.md#personal_toolkit_oauth_v1_test_saved_personal_connection) | **POST** /toolkit/v1/personal-toolkit-configs/{toolkit_id}/test-connection | Test Saved Personal Connection


# **personal_toolkit_oauth_v1_connect_personal_oauth**
> OAuthAuthorizeResponse personal_toolkit_oauth_v1_connect_personal_oauth(toolkit_id)

Connect Personal Oauth

Connect the exact active owner's canonical MCP-backed connection.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.o_auth_authorize_response import OAuthAuthorizeResponse
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
    api_instance = azentspublicclient.PersonalToolkitOAuthV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Connect Personal Oauth
        api_response = api_instance.personal_toolkit_oauth_v1_connect_personal_oauth(toolkit_id)
        print("The response of PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_connect_personal_oauth:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_connect_personal_oauth: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 

### Return type

[**OAuthAuthorizeResponse**](OAuthAuthorizeResponse.md)

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

# **personal_toolkit_oauth_v1_disconnect_personal_oauth**
> personal_toolkit_oauth_v1_disconnect_personal_oauth(toolkit_id)

Disconnect Personal Oauth

Delete only the current owner's local MCP credentials and pending admission.

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
    api_instance = azentspublicclient.PersonalToolkitOAuthV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Disconnect Personal Oauth
        api_instance.personal_toolkit_oauth_v1_disconnect_personal_oauth(toolkit_id)
    except Exception as e:
        print("Exception when calling PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_disconnect_personal_oauth: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_toolkit_oauth_v1_exchange_personal_oauth**
> personal_toolkit_oauth_v1_exchange_personal_oauth(toolkit_id, personal_o_auth_exchange_request)

Exchange Personal Oauth

Publish only after owner/Auth Session/source callback binding is verified.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_o_auth_exchange_request import PersonalOAuthExchangeRequest
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
    api_instance = azentspublicclient.PersonalToolkitOAuthV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    personal_o_auth_exchange_request = azentspublicclient.PersonalOAuthExchangeRequest() # PersonalOAuthExchangeRequest | 

    try:
        # Exchange Personal Oauth
        api_instance.personal_toolkit_oauth_v1_exchange_personal_oauth(toolkit_id, personal_o_auth_exchange_request)
    except Exception as e:
        print("Exception when calling PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_exchange_personal_oauth: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **personal_o_auth_exchange_request** | [**PersonalOAuthExchangeRequest**](PersonalOAuthExchangeRequest.md)|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_toolkit_oauth_v1_test_personal_connection**
> TestConnectionResponse personal_toolkit_oauth_v1_test_personal_connection(personal_connection_test_request)

Test Personal Connection

Test common unsaved fields or an exact-owner saved credential merge.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_connection_test_request import PersonalConnectionTestRequest
from azentspublicclient.models.test_connection_response import TestConnectionResponse
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
    api_instance = azentspublicclient.PersonalToolkitOAuthV1Api(api_client)
    personal_connection_test_request = azentspublicclient.PersonalConnectionTestRequest() # PersonalConnectionTestRequest | 

    try:
        # Test Personal Connection
        api_response = api_instance.personal_toolkit_oauth_v1_test_personal_connection(personal_connection_test_request)
        print("The response of PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_test_personal_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_test_personal_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **personal_connection_test_request** | [**PersonalConnectionTestRequest**](PersonalConnectionTestRequest.md)|  | 

### Return type

[**TestConnectionResponse**](TestConnectionResponse.md)

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

# **personal_toolkit_oauth_v1_test_saved_personal_connection**
> TestConnectionResponse personal_toolkit_oauth_v1_test_saved_personal_connection(toolkit_id)

Test Saved Personal Connection

Test this account's saved connection through its normal Provider.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.test_connection_response import TestConnectionResponse
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
    api_instance = azentspublicclient.PersonalToolkitOAuthV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Test Saved Personal Connection
        api_response = api_instance.personal_toolkit_oauth_v1_test_saved_personal_connection(toolkit_id)
        print("The response of PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_test_saved_personal_connection:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitOAuthV1Api->personal_toolkit_oauth_v1_test_saved_personal_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 

### Return type

[**TestConnectionResponse**](TestConnectionResponse.md)

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

