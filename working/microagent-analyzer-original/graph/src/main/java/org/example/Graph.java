package org.example;

import java.util.*;
import java.io.File;
import java.io.IOException;

/**
 * Represents a graph of class relationships
 */
public class Graph {
    // Map of class name to its relationships
    private Map<String, ClassNode> nodes = new HashMap<>();
    
    // Map of class name to its detailed information
    private Map<String, ClassDetails> classDetails = new HashMap<>();
    
    public static void main(String[] args) {
        if (args.length < 1 || args[0].equals("-h") || args[0].equals("--help")) {
            printUsage();
            return;
        }
        
        // Collect source paths and validate they exist
        List<String> sourcePaths = new ArrayList<>();
        int argIndex = 0;
        
        // Process source paths (all arguments before the first flag starting with --)
        while (argIndex < args.length && !args[argIndex].startsWith("--")) {
            String path = args[argIndex];
            File pathDir = new File(path);
        
            if (!pathDir.exists() || !pathDir.isDirectory()) {
                System.err.println("Error: The specified path does not exist or is not a directory: " + path);
                printUsage();
                return;
            }
            
            sourcePaths.add(path);
            argIndex++;
        }
        
        if (sourcePaths.isEmpty()) {
            System.err.println("Error: At least one source path must be specified.");
            printUsage();
            return;
        }
        
        // Default output files
        String jsonOutputFile = "relationships.json";
        String dotOutputFile = "relationships.dot";
        String jpgOutputFile = "relationships.jpg";
        boolean exportDot = true;
        boolean exportJpg = true;
        int imageWidth = 4000; // Default high resolution width
        
        // Process command line arguments
        for (int i = argIndex; i < args.length; i++) {
            if (args[i].equals("--json") && i + 1 < args.length) {
                jsonOutputFile = args[++i];
            } else if (args[i].equals("--dot") && i + 1 < args.length) {
                dotOutputFile = args[++i];
                exportDot = true;
            } else if (args[i].equals("--jpg") && i + 1 < args.length) {
                jpgOutputFile = args[++i];
                exportJpg = true;
            } else if (args[i].equals("--width") && i + 1 < args.length) {
                try {
                    imageWidth = Integer.parseInt(args[++i]);
                } catch (NumberFormatException e) {
                    System.err.println("Error: Invalid width value. Using default: " + imageWidth);
                }
            } else if (args[i].equals("--no-dot")) {
                exportDot = false;
            } else if (args[i].equals("--no-jpg")) {
                exportJpg = false;
            }
        }
        
        System.out.println("Analyzing Java project at paths:");
        for (String path : sourcePaths) {
            System.out.println("  - " + path);
        }
        System.out.println("Results will be exported to JSON: " + jsonOutputFile);
        if (exportDot) {
            System.out.println("DOT file will be generated: " + dotOutputFile);
        }
        if (exportJpg) {
            System.out.println("JPG image will be generated: " + jpgOutputFile);
        }
        
        // Create a single analyzer to handle all paths
        ClassRelationshipAnalyzer analyzer = new ClassRelationshipAnalyzer(sourcePaths);
        analyzer.analyze();
        analyzer.printRelationships();
        analyzer.exportToJson(jsonOutputFile);
        
        // Export to DOT and JPG if requested
        if (exportDot || exportJpg) {
            GraphExporter exporter = new GraphExporter(analyzer.getGraph(), imageWidth);
            
            try {
                if (exportDot) {
                    exporter.exportToDot(dotOutputFile);
                }
                
                if (exportJpg) {
                    exporter.exportToJpg(jpgOutputFile);
                }
            } catch (IOException e) {
                System.err.println("Error exporting graph: " + e.getMessage());
                e.printStackTrace();
            }
        }
    }
    
    private static void printUsage() {
        System.out.println("Usage: java -jar java-class-analyzer.jar <path-to-java-project> [<path-to-java-project-2> ...] [options]");
        System.out.println();
        System.out.println("Arguments:");
        System.out.println("  <path-to-java-project>  One or more paths to Java source directories to analyze");
        System.out.println();
        System.out.println("Options:");
        System.out.println("  --json <file>           Path to the output JSON file (default: relationships.json)");
        System.out.println("  --dot <file>            Path to the output DOT file (default: relationships.dot)");
        System.out.println("  --jpg <file>            Path to the output JPG file (default: relationships.jpg)");
        System.out.println("  --width <pixels>        Width of the output image in pixels (default: 4000)");
        System.out.println("  --no-dot                Skip DOT file generation");
        System.out.println("  --no-jpg                Skip JPG file generation");
        System.out.println();
        System.out.println("Examples:");
        System.out.println("  java -jar java-class-analyzer.jar /path/to/myproject");
        System.out.println("  java -jar java-class-analyzer.jar /path/to/module1 /path/to/module2 --json multi-module.json");
        System.out.println("  java -jar java-class-analyzer.jar /path/to/myproject --json my-project.json --jpg my-project.jpg");
    }
    
    /**
     * Add a node to the graph
     */
    public void addNode(String className) {
        nodes.putIfAbsent(className, new ClassNode(className));
        classDetails.putIfAbsent(className, new ClassDetails(className));
    }
    
    /**
     * Remove a node from the graph
     */
    public void removeNode(String className) {
        nodes.remove(className);
        classDetails.remove(className);
    }
    
    /**
     * Add a relationship between two classes
     */
    public void addRelationship(String sourceClass, String targetClass, RelationshipType type) {
        // Skip if either class is null or empty
        if (sourceClass == null || sourceClass.isEmpty() || targetClass == null || targetClass.isEmpty()) {
            return;
        }
        
        // Skip self-relationships
        if (sourceClass.equals(targetClass)) {
            return;
        }
        
        // Add nodes for source and target classes
        addNode(sourceClass);
        addNode(targetClass);
        
        // Add the relationship
        ClassNode source = nodes.get(sourceClass);
        source.addRelationship(targetClass, type);
    }
    
    /**
     * Get all relationships in the graph
     */
    public Map<String, ClassNode> getNodes() {
        return nodes;
    }
    
    /**
     * Get all class details in the graph
     */
    public Map<String, ClassDetails> getClassDetails() {
        return classDetails;
    }
    
    /**
     * Get details for a specific class
     */
    public ClassDetails getClassDetail(String className) {
        return classDetails.get(className);
    }
    
    /**
     * Get all relationships for a specific class
     */
    public List<Relationship> getRelationships(String className) {
        ClassNode node = nodes.get(className);
        return node != null ? node.getRelationships() : Collections.emptyList();
    }
    
    /**
     * Get all classes that have a specific relationship with the given class
     */
    public Set<String> getRelatedClasses(String className, RelationshipType type) {
        Set<String> relatedClasses = new HashSet<>();
        ClassNode node = nodes.get(className);
        
        if (node != null) {
            for (Relationship rel : node.getRelationships()) {
                if (rel.getType() == type) {
                    relatedClasses.add(rel.getTargetClass());
                }
            }
        }
        
        return relatedClasses;
    }
}