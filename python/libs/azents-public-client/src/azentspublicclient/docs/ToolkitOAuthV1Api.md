# azentspublicclient.ToolkitOAuthV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**toolkit_oauth_v1_connect_oauth**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_connect_oauth) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/connect | Connect Oauth
[**toolkit_oauth_v1_disconnect_oauth_connection**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_disconnect_oauth_connection) | **DELETE** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/connection | Disconnect Oauth Connection
[**toolkit_oauth_v1_exchange_oauth_connection**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_exchange_oauth_connection) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/exchange | Exchange Oauth Connection
[**toolkit_oauth_v1_get_github_platform_install_url**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_get_github_platform_install_url) | **GET** /toolkit/v1/workspaces/{handle}/github/platform-install-url | Get Github Platform Install Url
[**toolkit_oauth_v1_get_github_platform_installations**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_get_github_platform_installations) | **POST** /toolkit/v1/workspaces/{handle}/github/platform-installations | Get Github Platform Installations
[**toolkit_oauth_v1_get_github_platform_oauth_url**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_get_github_platform_oauth_url) | **GET** /toolkit/v1/workspaces/{handle}/github/platform-oauth-url | Get Github Platform Oauth Url
[**toolkit_oauth_v1_test_connection_saved**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_test_connection_saved) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/test-connection | Test Connection Saved
[**toolkit_oauth_v1_test_connection_unsaved**](ToolkitOAuthV1Api.md#toolkit_oauth_v1_test_connection_unsaved) | **POST** /toolkit/v1/workspaces/{handle}/toolkit-configs/test-connection | Test Connection Unsaved


# **toolkit_oauth_v1_connect_oauth**
> OAuthAuthorizeResponse toolkit_oauth_v1_connect_oauth(handle, toolkit_config_id)

Connect Oauth

Create a manager-owned toolkit OAuth authorization URL.

Requires Toolkit write permission.

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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |
    toolkit_config_id = 'toolkit_config_id_example' # str |

    try:
        # Connect Oauth
        api_response = api_instance.toolkit_oauth_v1_connect_oauth(handle, toolkit_config_id)
        print("The response of ToolkitOAuthV1Api->toolkit_oauth_v1_connect_oauth:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_connect_oauth: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **toolkit_config_id** | **str**|  |

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

# **toolkit_oauth_v1_disconnect_oauth_connection**
> toolkit_oauth_v1_disconnect_oauth_connection(handle, toolkit_config_id)

Disconnect Oauth Connection

Delete a toolkit-level OAuth connection.

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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |
    toolkit_config_id = 'toolkit_config_id_example' # str |

    try:
        # Disconnect Oauth Connection
        api_instance.toolkit_oauth_v1_disconnect_oauth_connection(handle, toolkit_config_id)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_disconnect_oauth_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **toolkit_config_id** | **str**|  |

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

# **toolkit_oauth_v1_exchange_oauth_connection**
> toolkit_oauth_v1_exchange_oauth_connection(handle, toolkit_config_id, o_auth_exchange_request)

Exchange Oauth Connection

Exchange authorization code for a toolkit-level OAuth connection.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.o_auth_exchange_request import OAuthExchangeRequest
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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |
    toolkit_config_id = 'toolkit_config_id_example' # str |
    o_auth_exchange_request = azentspublicclient.OAuthExchangeRequest() # OAuthExchangeRequest |

    try:
        # Exchange Oauth Connection
        api_instance.toolkit_oauth_v1_exchange_oauth_connection(handle, toolkit_config_id, o_auth_exchange_request)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_exchange_oauth_connection: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **toolkit_config_id** | **str**|  |
 **o_auth_exchange_request** | [**OAuthExchangeRequest**](OAuthExchangeRequest.md)|  |

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

# **toolkit_oauth_v1_get_github_platform_install_url**
> GitHubPlatformInstallUrlResponse toolkit_oauth_v1_get_github_platform_install_url(handle)

Get Github Platform Install Url

Return the GitHub Platform App installation URL.

Creates a JWT with Platform App credentials configured on the server,
calls the GitHub API to fetch the App slug, then builds the installation URL.
Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_platform_install_url_response import GitHubPlatformInstallUrlResponse
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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Get Github Platform Install Url
        api_response = api_instance.toolkit_oauth_v1_get_github_platform_install_url(handle)
        print("The response of ToolkitOAuthV1Api->toolkit_oauth_v1_get_github_platform_install_url:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_get_github_platform_install_url: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**GitHubPlatformInstallUrlResponse**](GitHubPlatformInstallUrlResponse.md)

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

# **toolkit_oauth_v1_get_github_platform_installations**
> GitHubPlatformInstallationsResponse toolkit_oauth_v1_get_github_platform_installations(handle, git_hub_platform_installations_request)

Get Github Platform Installations

Return installations accessible with the user GitHub OAuth token.

Exchanges GitHub App OAuth code for an access token, calls
``GET /user/installations``, and returns only installations the user can access.
Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_platform_installations_request import GitHubPlatformInstallationsRequest
from azentspublicclient.models.git_hub_platform_installations_response import GitHubPlatformInstallationsResponse
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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |
    git_hub_platform_installations_request = azentspublicclient.GitHubPlatformInstallationsRequest() # GitHubPlatformInstallationsRequest |

    try:
        # Get Github Platform Installations
        api_response = api_instance.toolkit_oauth_v1_get_github_platform_installations(handle, git_hub_platform_installations_request)
        print("The response of ToolkitOAuthV1Api->toolkit_oauth_v1_get_github_platform_installations:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_get_github_platform_installations: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **git_hub_platform_installations_request** | [**GitHubPlatformInstallationsRequest**](GitHubPlatformInstallationsRequest.md)|  |

### Return type

[**GitHubPlatformInstallationsResponse**](GitHubPlatformInstallationsResponse.md)

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

# **toolkit_oauth_v1_get_github_platform_oauth_url**
> GitHubPlatformOAuthUrlResponse toolkit_oauth_v1_get_github_platform_oauth_url(handle)

Get Github Platform Oauth Url

Return the GitHub Platform App OAuth authorization URL.

Starts an OAuth flow so the user can log in to GitHub and list their own
installations. Requires Toolkit write permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_platform_o_auth_url_response import GitHubPlatformOAuthUrlResponse
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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Get Github Platform Oauth Url
        api_response = api_instance.toolkit_oauth_v1_get_github_platform_oauth_url(handle)
        print("The response of ToolkitOAuthV1Api->toolkit_oauth_v1_get_github_platform_oauth_url:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_get_github_platform_oauth_url: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**GitHubPlatformOAuthUrlResponse**](GitHubPlatformOAuthUrlResponse.md)

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

# **toolkit_oauth_v1_test_connection_saved**
> TestConnectionResponse toolkit_oauth_v1_test_connection_saved(toolkit_config_id, handle)

Test Connection Saved

Test the connection of a stored Toolkit.

Requires Toolkit read permission.

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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    toolkit_config_id = 'toolkit_config_id_example' # str |
    handle = 'handle_example' # str |

    try:
        # Test Connection Saved
        api_response = api_instance.toolkit_oauth_v1_test_connection_saved(toolkit_config_id, handle)
        print("The response of ToolkitOAuthV1Api->toolkit_oauth_v1_test_connection_saved:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_test_connection_saved: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_config_id** | **str**|  |
 **handle** | **str**|  |

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

# **toolkit_oauth_v1_test_connection_unsaved**
> TestConnectionResponse toolkit_oauth_v1_test_connection_unsaved(handle, test_connection_request)

Test Connection Unsaved

Test the connection for Toolkit settings.

When ``toolkit_config_id`` exists, load credentials stored in DB and override
them with credentials from the body, prioritizing form values in edit mode.

Requires Toolkit read permission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.test_connection_request import TestConnectionRequest
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
    api_instance = azentspublicclient.ToolkitOAuthV1Api(api_client)
    handle = 'handle_example' # str |
    test_connection_request = azentspublicclient.TestConnectionRequest() # TestConnectionRequest |

    try:
        # Test Connection Unsaved
        api_response = api_instance.toolkit_oauth_v1_test_connection_unsaved(handle, test_connection_request)
        print("The response of ToolkitOAuthV1Api->toolkit_oauth_v1_test_connection_unsaved:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling ToolkitOAuthV1Api->toolkit_oauth_v1_test_connection_unsaved: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **test_connection_request** | [**TestConnectionRequest**](TestConnectionRequest.md)|  |

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

