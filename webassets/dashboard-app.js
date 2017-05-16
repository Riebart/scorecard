var myApp = angular.module('dashboardApp', ['ngResource']);

myApp.filter("toArray", function(){
    return function(obj) {
        var result = [];
        angular.forEach(obj, function(val, key) {
            result.push({"team": key, "score": val});
        });
        return result;
    };
});

myApp.controller('scoreboardController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {

    $scope.init = function () {
        // The scores, on initialization, are an empty list.
        $scope.scores = {};
        $scope.team_names = {};
        $scope.ScoresResource = $resource(API_ENDPOINT + "/score/:team");
    };

    $scope.PopulateScores = function () {
        for (i in TEAMS) {
            t = TEAMS[i];
            team_id = null;
            if (typeof (t) == "object") {
                team_id = t.team_id;
                team_name = t.team_name;
                $scope.team_names[team_id] = team_name;
            }
            else {
                team_id = t;
                team_name = t.toString();
                $scope.team_names[team_id] = team_name;
            }
            // For each team, retrieve the score for that team.
            $scope.ScoresResource.get({
                team: team_id.toString()
            }, function (score) {
                $scope.scores[$scope.team_names[score.team]] = score.score;
            });
        }
        return true;
    }

    $scope.ScoresRefresh = function () {
        $scope.PopulateScores();
        var poll = function () {
            $timeout(function () {
                if ($scope.PopulateScores()) {
                    poll();
                }
            }, 10000);
        };
        poll();
    };

    $scope.$on('async_init', function () {
        $scope.init();
        $scope.ScoresRefresh();
    });

    $scope.$emit('async_init');
}]);
