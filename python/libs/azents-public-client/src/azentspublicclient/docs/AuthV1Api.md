# azentspublicclient.AuthV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**auth_v1_get_login_methods**](AuthV1Api.md#auth_v1_get_login_methods) | **GET** /auth/v1/login/methods | Get Login Methods
[**auth_v1_get_signup_status**](AuthV1Api.md#auth_v1_get_signup_status) | **GET** /auth/v1/signup/status | Get Signup Status
[**auth_v1_login_with_password**](AuthV1Api.md#auth_v1_login_with_password) | **POST** /auth/v1/login/password | Login With Password
[**auth_v1_logout**](AuthV1Api.md#auth_v1_logout) | **POST** /auth/v1/logout | Logout
[**auth_v1_preview_password_reset_token**](AuthV1Api.md#auth_v1_preview_password_reset_token) | **POST** /auth/v1/password-reset-tokens/preview | Preview Password Reset Token
[**auth_v1_preview_signup_token**](AuthV1Api.md#auth_v1_preview_signup_token) | **POST** /auth/v1/signup-tokens/preview | Preview Signup Token
[**auth_v1_redeem_password_reset_token**](AuthV1Api.md#auth_v1_redeem_password_reset_token) | **POST** /auth/v1/password-reset-tokens/redeem | Redeem Password Reset Token
[**auth_v1_redeem_signup_token**](AuthV1Api.md#auth_v1_redeem_signup_token) | **POST** /auth/v1/signup-tokens/redeem | Redeem Signup Token
[**auth_v1_refresh_token**](AuthV1Api.md#auth_v1_refresh_token) | **POST** /auth/v1/token/refresh | Refresh Token
[**auth_v1_request_signup_email**](AuthV1Api.md#auth_v1_request_signup_email) | **POST** /auth/v1/signup/email | Request Signup Email
[**auth_v1_send_code**](AuthV1Api.md#auth_v1_send_code) | **POST** /auth/v1/email/send-code | Send Code
[**auth_v1_verify_code**](AuthV1Api.md#auth_v1_verify_code) | **POST** /auth/v1/email/verify | Verify Code


# **auth_v1_get_login_methods**
> LoginMethodsResponse auth_v1_get_login_methods(email)

Get Login Methods

Get available login methods for an email.

### Example


```python
import azentspublicclient
from azentspublicclient.models.login_methods_response import LoginMethodsResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    email = 'email_example' # str | 

    try:
        # Get Login Methods
        api_response = api_instance.auth_v1_get_login_methods(email)
        print("The response of AuthV1Api->auth_v1_get_login_methods:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_get_login_methods: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **email** | **str**|  | 

### Return type

[**LoginMethodsResponse**](LoginMethodsResponse.md)

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

# **auth_v1_get_signup_status**
> SignupStatusResponse auth_v1_get_signup_status()

Get Signup Status

Return whether signup UX can be shown.

### Example


```python
import azentspublicclient
from azentspublicclient.models.signup_status_response import SignupStatusResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)

    try:
        # Get Signup Status
        api_response = api_instance.auth_v1_get_signup_status()
        print("The response of AuthV1Api->auth_v1_get_signup_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_get_signup_status: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**SignupStatusResponse**](SignupStatusResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_login_with_password**
> PasswordLoginResponse auth_v1_login_with_password(password_login_request)

Login With Password

Log in with email and password.

### Example


```python
import azentspublicclient
from azentspublicclient.models.password_login_request import PasswordLoginRequest
from azentspublicclient.models.password_login_response import PasswordLoginResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    password_login_request = azentspublicclient.PasswordLoginRequest() # PasswordLoginRequest | 

    try:
        # Login With Password
        api_response = api_instance.auth_v1_login_with_password(password_login_request)
        print("The response of AuthV1Api->auth_v1_login_with_password:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_login_with_password: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **password_login_request** | [**PasswordLoginRequest**](PasswordLoginRequest.md)|  | 

### Return type

[**PasswordLoginResponse**](PasswordLoginResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_logout**
> auth_v1_logout()

Logout

Revoke the current session.

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
    api_instance = azentspublicclient.AuthV1Api(api_client)

    try:
        # Logout
        api_instance.auth_v1_logout()
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_logout: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: Not defined

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_preview_password_reset_token**
> PreviewPasswordResetTokenResponse auth_v1_preview_password_reset_token(preview_password_reset_token_request)

Preview Password Reset Token

Check password reset token status.

### Example


```python
import azentspublicclient
from azentspublicclient.models.preview_password_reset_token_request import PreviewPasswordResetTokenRequest
from azentspublicclient.models.preview_password_reset_token_response import PreviewPasswordResetTokenResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    preview_password_reset_token_request = azentspublicclient.PreviewPasswordResetTokenRequest() # PreviewPasswordResetTokenRequest | 

    try:
        # Preview Password Reset Token
        api_response = api_instance.auth_v1_preview_password_reset_token(preview_password_reset_token_request)
        print("The response of AuthV1Api->auth_v1_preview_password_reset_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_preview_password_reset_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **preview_password_reset_token_request** | [**PreviewPasswordResetTokenRequest**](PreviewPasswordResetTokenRequest.md)|  | 

### Return type

[**PreviewPasswordResetTokenResponse**](PreviewPasswordResetTokenResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_preview_signup_token**
> PreviewSignupTokenResponse auth_v1_preview_signup_token(preview_signup_token_request)

Preview Signup Token

Check signup token status.

### Example


```python
import azentspublicclient
from azentspublicclient.models.preview_signup_token_request import PreviewSignupTokenRequest
from azentspublicclient.models.preview_signup_token_response import PreviewSignupTokenResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    preview_signup_token_request = azentspublicclient.PreviewSignupTokenRequest() # PreviewSignupTokenRequest | 

    try:
        # Preview Signup Token
        api_response = api_instance.auth_v1_preview_signup_token(preview_signup_token_request)
        print("The response of AuthV1Api->auth_v1_preview_signup_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_preview_signup_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **preview_signup_token_request** | [**PreviewSignupTokenRequest**](PreviewSignupTokenRequest.md)|  | 

### Return type

[**PreviewSignupTokenResponse**](PreviewSignupTokenResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_redeem_password_reset_token**
> RedeemPasswordResetTokenResponse auth_v1_redeem_password_reset_token(redeem_password_reset_token_request)

Redeem Password Reset Token

Set a password from a password reset token.

### Example


```python
import azentspublicclient
from azentspublicclient.models.redeem_password_reset_token_request import RedeemPasswordResetTokenRequest
from azentspublicclient.models.redeem_password_reset_token_response import RedeemPasswordResetTokenResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    redeem_password_reset_token_request = azentspublicclient.RedeemPasswordResetTokenRequest() # RedeemPasswordResetTokenRequest | 

    try:
        # Redeem Password Reset Token
        api_response = api_instance.auth_v1_redeem_password_reset_token(redeem_password_reset_token_request)
        print("The response of AuthV1Api->auth_v1_redeem_password_reset_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_redeem_password_reset_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **redeem_password_reset_token_request** | [**RedeemPasswordResetTokenRequest**](RedeemPasswordResetTokenRequest.md)|  | 

### Return type

[**RedeemPasswordResetTokenResponse**](RedeemPasswordResetTokenResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_redeem_signup_token**
> RedeemSignupTokenResponse auth_v1_redeem_signup_token(redeem_signup_token_request)

Redeem Signup Token

Create an account from a signup token and issue a JWT.

### Example


```python
import azentspublicclient
from azentspublicclient.models.redeem_signup_token_request import RedeemSignupTokenRequest
from azentspublicclient.models.redeem_signup_token_response import RedeemSignupTokenResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    redeem_signup_token_request = azentspublicclient.RedeemSignupTokenRequest() # RedeemSignupTokenRequest | 

    try:
        # Redeem Signup Token
        api_response = api_instance.auth_v1_redeem_signup_token(redeem_signup_token_request)
        print("The response of AuthV1Api->auth_v1_redeem_signup_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_redeem_signup_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **redeem_signup_token_request** | [**RedeemSignupTokenRequest**](RedeemSignupTokenRequest.md)|  | 

### Return type

[**RedeemSignupTokenResponse**](RedeemSignupTokenResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_refresh_token**
> RefreshTokenResponse auth_v1_refresh_token(refresh_token_request)

Refresh Token

Issue new tokens from a refresh token.

### Example


```python
import azentspublicclient
from azentspublicclient.models.refresh_token_request import RefreshTokenRequest
from azentspublicclient.models.refresh_token_response import RefreshTokenResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    refresh_token_request = azentspublicclient.RefreshTokenRequest() # RefreshTokenRequest | 

    try:
        # Refresh Token
        api_response = api_instance.auth_v1_refresh_token(refresh_token_request)
        print("The response of AuthV1Api->auth_v1_refresh_token:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_refresh_token: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **refresh_token_request** | [**RefreshTokenRequest**](RefreshTokenRequest.md)|  | 

### Return type

[**RefreshTokenResponse**](RefreshTokenResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_request_signup_email**
> RequestSignupEmailResponse auth_v1_request_signup_email(request_signup_email_request)

Request Signup Email

Send a signup link by email.

### Example


```python
import azentspublicclient
from azentspublicclient.models.request_signup_email_request import RequestSignupEmailRequest
from azentspublicclient.models.request_signup_email_response import RequestSignupEmailResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    request_signup_email_request = azentspublicclient.RequestSignupEmailRequest() # RequestSignupEmailRequest | 

    try:
        # Request Signup Email
        api_response = api_instance.auth_v1_request_signup_email(request_signup_email_request)
        print("The response of AuthV1Api->auth_v1_request_signup_email:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_request_signup_email: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **request_signup_email_request** | [**RequestSignupEmailRequest**](RequestSignupEmailRequest.md)|  | 

### Return type

[**RequestSignupEmailResponse**](RequestSignupEmailResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_send_code**
> SendCodeResponse auth_v1_send_code(send_code_request)

Send Code

Send an email verification code.

### Example


```python
import azentspublicclient
from azentspublicclient.models.send_code_request import SendCodeRequest
from azentspublicclient.models.send_code_response import SendCodeResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    send_code_request = azentspublicclient.SendCodeRequest() # SendCodeRequest | 

    try:
        # Send Code
        api_response = api_instance.auth_v1_send_code(send_code_request)
        print("The response of AuthV1Api->auth_v1_send_code:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_send_code: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **send_code_request** | [**SendCodeRequest**](SendCodeRequest.md)|  | 

### Return type

[**SendCodeResponse**](SendCodeResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **auth_v1_verify_code**
> VerifyCodeResponse auth_v1_verify_code(verify_code_request)

Verify Code

Verify an authentication code and issue a JWT.

### Example


```python
import azentspublicclient
from azentspublicclient.models.verify_code_request import VerifyCodeRequest
from azentspublicclient.models.verify_code_response import VerifyCodeResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)


# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.AuthV1Api(api_client)
    verify_code_request = azentspublicclient.VerifyCodeRequest() # VerifyCodeRequest | 

    try:
        # Verify Code
        api_response = api_instance.auth_v1_verify_code(verify_code_request)
        print("The response of AuthV1Api->auth_v1_verify_code:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AuthV1Api->auth_v1_verify_code: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **verify_code_request** | [**VerifyCodeRequest**](VerifyCodeRequest.md)|  | 

### Return type

[**VerifyCodeResponse**](VerifyCodeResponse.md)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

