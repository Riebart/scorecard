var myApp = angular.module('submissionApp', ['ngResource']);

myApp.controller('submissionController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {

    $scope.init = function () {
        $scope.submission_status = null;
        $scope.usernameText = "";
        $scope.emailText = "";
        $scope.submitting = false;
        $scope.FlagResource = $resource(API_ENDPOINT + "/register");
    };

    $scope.inputKeyPressed = function (keyEvent) {
        $scope.submission_status = null;
    };

    $scope.submitFlag = function () {
        if (($scope.emailText == null) || ($scope.emailText == "")) {
            $scope.submission_status = 'failure';
            return false;
        }
        if (($scope.usernameText == null) || ($scope.usernameText == "")) {
            $scope.submission_status = 'failure';
            return false;
        }

        $scope.submitting = true;
        $scope.FlagResource.save({
            email: $scope.emailText,
            username: $scope.usernameText
        }, function (response) {
            $scope.submitting = false;
            $scope.submission_status = response.result;
        });
    };

    $scope.$on('async_init', function () {
        $scope.init();
    });

    $scope.$emit('async_init');
}]);
