import setuptools
setuptools.setup(
    name="infrastructure",
    version="0.0.1",

    description="A sample CDK Python app",

    author="author",

    package_dir={"": "infrastructure"},
    packages=setuptools.find_packages(where="infrastructure"),

    install_requires=[
        "aws-cdk.core",
        "aws-cdk.aws_apigateway",
        "aws-cdk.aws_cognito",
        "aws-cdk.aws_dynamodb",
        "aws-cdk.aws_iam",
        "aws-cdk.aws_lambda",
        "aws-cdk.aws_secretsmanager",
        "urllib3"
    ],

    python_requires=">=3.6",

    classifiers=[
        "Development Status :: 4 - Beta",

        "Intended Audience :: Developers",

        "License :: OSI Approved :: Apache Software License",

        "Programming Language :: JavaScript",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",

        "Topic :: Software Development :: Code Generators",
        "Topic :: Utilities",

        "Typing :: Typed",
    ],
)
